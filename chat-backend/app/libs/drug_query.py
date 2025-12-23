from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from typing import Protocol, final

import httpx
from pydantic import BaseModel, ValidationError

from app.libs.expected import Expected


def create_kv_abstract(v: dict[str, str | None]) -> str:
    root = ET.Element("div")
    for key, value in v.items():
        elm = ET.SubElement(root, "p")
        elm.text = f"{key}: {value}"
    return ET.tostring(root).decode()


def stitch_line(v: list[str]) -> str:
    root = ET.Element("div")
    for e in v:
        elm = ET.SubElement(root, "p")
        elm.text = e
    return ET.tostring(root).decode()


class AgentError(BaseModel):
    """Container for agent-related error information."""

    message: str


class DoiResolver:
    async def resolve(self, doi: str, client: httpx.AsyncClient) -> str:
        res = await client.get(f"https://dx.doi.org/{doi}", follow_redirects=False)
        return res.headers.get("LOCATION")


class ClinicalTrialsResolver:
    async def resolve(self, id: str, client: httpx.AsyncClient) -> str:
        return f"https://clinicaltrials.gov/study/{id}"


class PublicationResult(BaseModel):
    title: str
    source: str
    abstract: str | None
    authors: list[str]
    link: str | None

    @staticmethod
    def create_expected(
        value: list[PublicationResult] | AgentError,
    ) -> Expected[list["PublicationResult"], AgentError]:
        return Expected(list, AgentError, value)

    async def to_xml(self, client: httpx.AsyncClient):
        root = ET.Element("publication", src=self.source, title=self.title)

        def create_elem(tag: str, text: str) -> ET.Element:
            elm = ET.Element(tag)
            elm.text = text
            return elm

        if self.abstract is not None:
            root.append(create_elem("abstract", text=self.abstract))
        authors = ET.Element("author_list")
        for author in self.authors:
            authors.append(create_elem("author", text=author))
        root.append(authors)
        if self.link is not None:
            root.append(create_elem("link", text=self.link))
        return ET.tostring(root).decode()


class PublicationQuery(Protocol):
    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]: ...


@final
class PubmedQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count
        self.source = "Pubmed"

    async def query_content(
        self, client: httpx.AsyncClient, ids: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"id": ",".join(ids), "db": "pubmed"},
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        parsed_res = ET.fromstring(res.text)
        summaries: list[PublicationResult] = []
        for article in parsed_res.findall("PubmedArticle"):
            pub_year = article.find("MedlineCitation/Article/Journal/PubDate/Year")
            pub_month = article.find("MedlineCitation/Article/Journal/PubDate/Month")
            pub_day = article.find("MedlineCitation/Article/Journal/PubDate/Day")
            title = article.find("MedlineCitation/Article/ArticleTitle")
            abstract = article.find("MedlineCitation/Article/Abstract/AbstractText")
            authors = []
            pub_date = (
                f"{pub_year}-{pub_month}-{pub_day}"
                if pub_year is not None
                and pub_month is not None
                and pub_day is not None
                else None
            )
            doi = article.find("MedlineCitation/Article/ELocationID[@EIdType='doi']")
            if doi is not None and doi.text is not None:
                doi = await DoiResolver().resolve(doi.text, client)
            try:
                summaries.append(
                    PublicationResult.model_validate(
                        {
                            "pub_date": pub_date,
                            "title": title.text if title is not None else None,
                            "authors": authors,
                            "link": doi,
                            "abstract": abstract.text if abstract is not None else None,
                            "source": self.source,
                        }
                    )
                )
            except ValidationError as e:
                logging.error(f"PubmedQuery: {str(e)}")
                continue
        return PublicationResult.create_expected(summaries)

    async def query_ids(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "term": " AND ".join([kw.replace(" ", "+") for kw in kws]),
                "retmax": str(self.res_count),
                # "retstart": self.res_count * (page - 1),
            },
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        # res.text is an xml text, lets parse and get all the Id
        parsed_res = ET.fromstring(res.text)
        ids = [id.text for id in parsed_res.findall(".//Id") if id.text is not None]
        if not ids:
            return PublicationResult.create_expected([])
        content_expected = await self.query_content(client, ids)
        if content_expected.has_value():
            return PublicationResult.create_expected(content_expected.value())
        return PublicationResult.create_expected(content_expected.error())

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        publications = await self.query_ids(client, kws)
        if publications.has_value():
            return PublicationResult.create_expected(publications.value())
        return PublicationResult.create_expected(publications.error())


@final
class EuropePMCQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count
        self.source = "Europe Pubmed Central"

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": kws,
                "pageSize": self.res_count,
                "format": "json",
                "resultType": "core",
            },
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        parsed_res = json.loads(res.text)
        publications: list[PublicationResult] = []
        for record in parsed_res["resultList"]["result"]:
            doi = record.get("doi")
            if doi is not None:
                doi = await DoiResolver().resolve(doi, client)
            try:
                publications.append(
                    PublicationResult.model_validate(
                        {
                            "title": record.get("title"),
                            "abstract": record.get("abstractText"),
                            "source": self.source,
                            "authors": record.get("authorString", "").split(","),
                            "pub_date": record.get("firstPublicationDate", ""),
                            "link": doi,
                        }
                    )
                )
            except ValidationError as exc:
                logging.error(f"EuropePMCQuery: {exc}")
                continue
        return PublicationResult.create_expected(publications)


class ClinicalTrialsGov:
    def __init__(self, res_count: int = 5):
        self.res_count = 5

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={"pageSize": self.res_count, "query.term": " OR ".join(kws)},
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        parsed_res = json.loads(res.text)
        studies = parsed_res["studies"]
        publications: list[PublicationResult] = []
        for study in studies:
            try:
                abstract = study["protocolSection"].get(
                    "descriptionModule",
                    {"briefSummary": "", "detailedDescription": ""},
                )
                if abstract.get("detailedDescription") is None:
                    abstract = abstract.get("briefSummary", "")
                else:
                    abstract = abstract.get("detailedDescription")
                publications.append(
                    PublicationResult.model_validate(
                        {
                            "title": study["protocolSection"]["identificationModule"][
                                "briefTitle"
                            ],
                            "abstract": abstract,
                            "source": "Clinical Trials",
                            "authors": [
                                study["protocolSection"]["identificationModule"][
                                    "organization"
                                ]["fullName"]
                            ],
                            "pub_date": study["protocolSection"]["statusModule"][
                                "startDateStruct"
                            ]["date"],
                            "link": await ClinicalTrialsResolver().resolve(
                                study["protocolSection"]["identificationModule"][
                                    "nctId"
                                ],
                                client,
                            ),
                        }
                    )
                )
            except ValidationError as e:
                logging.error(f"ClinicalTrials: {e}")
                continue
        return PublicationResult.create_expected(publications)


@final
class PublicationQueryMaker:
    def __init__(self, qs: list[PublicationQuery]):
        self.qs = qs
        self.client = httpx.AsyncClient()

    async def query(
        self, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        results: list[PublicationResult] = []
        for q in self.qs:
            res = await q.query(self.client, kws)
            if not res.has_value():
                return res
            results.extend(res.value())
        return PublicationResult.create_expected(results)


class FDADrugIngredient(BaseModel):
    name: str
    strength: str


class FDADrug(BaseModel):
    sponsor_name: str
    application_number: str
    brand_name: str
    active_ingredients: list[FDADrugIngredient]
    dosage_form: str | None
    dosage_route: str | None
    marketing_status: str | None

    def to_publication(self) -> PublicationResult:
        return PublicationResult(
            title=self.brand_name,
            abstract=create_kv_abstract(
                {
                    "Application Number": self.application_number,
                    "Dosage Form": self.dosage_form,
                    "Dosage Route": self.dosage_route,
                    "Marketing Status": self.marketing_status,
                }
            )
            + stitch_line(
                [
                    "Active Ingredients: ",
                    *[f"- {v.name} {v.strength}" for v in self.active_ingredients],
                ]
            ),
            authors=[self.sponsor_name],
            source="OpenFDA",
            link=None,
        )

    @staticmethod
    def create_expected(
        v: list[FDADrug] | AgentError,
    ) -> Expected[list[FDADrug], AgentError]:
        return Expected(list, AgentError, v)


class OpenFDAQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://api.fda.gov/drug/drugsfda.json",
            params={
                "search": f"products.active_ingredients.name={' '.join([kw for kw in kws])}",
                "limit": 5,
            },
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        parsed_res = json.loads(res.text)
        drugs: list[FDADrug] = []
        for r in parsed_res["results"]:
            drugs.extend(
                [
                    FDADrug(
                        sponsor_name=r["sponsor_name"],
                        application_number=r["application_number"],
                        brand_name=product["brand_name"],
                        active_ingredients=[
                            FDADrugIngredient(name=x["name"], strength=x["strength"])
                            for x in product.get("active_ingredients", [])
                        ],
                        dosage_form=product.get("dosage_form"),
                        dosage_route=product.get("dosage_route"),
                        marketing_status=product.get("marketing_status"),
                    )
                    for product in r.get("products", [])
                ]
            )
        return PublicationResult.create_expected(
            [drug.to_publication() for drug in drugs]
        )


class ChemblQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://www.ebi.ac.uk/chembl/api/data/document/search",
            params={"q": " ".join(kws)},
        )
        if res.status_code > 299:
            return PublicationResult.create_expected(AgentError(message=res.text))
        response = ET.fromstring(res.text)
        summaries: list[PublicationResult] = []
        for document in response.findall(".//document"):
            abstract = document.find("abstract")
            authors = document.find("authors")
            doi = document.find("doi")
            title = document.find("title")
            pub_date = document.find("chembl_release/creation_date")
            if doi is not None and doi.text is not None and len(doi.text) != 0:
                doi = await DoiResolver().resolve(doi.text, client)
            else:
                doi = None
            try:
                summaries.append(
                    PublicationResult.model_validate(
                        {
                            "title": title.text if title is not None else None,
                            "pub_date": pub_date.text if pub_date is not None else None,
                            "authors": authors.text.split(",")
                            if authors is not None and authors.text is not None
                            else [],
                            "link": doi,
                            "abstract": abstract.text if abstract is not None else None,
                            "source": "CHEMBL",
                        }
                    )
                )
            except ValidationError as e:
                logging.error(f"PubmedQuery {str(e)}")
                continue
        return PublicationResult.create_expected(summaries)


class PubchemCompound(BaseModel):
    name: str
    iupac_name: str | None
    molecular_formula: str
    molecular_weight: float
    inchi: str
    id: str

    def to_publication(self) -> PublicationResult:
        return PublicationResult(
            title=self.name,
            source="Pubchem",
            abstract=create_kv_abstract(
                {
                    "IUPAC Name": self.iupac_name,
                    "Molecular Formula": self.molecular_formula,
                    "Molecular Weight": str(round(self.molecular_weight, 3)),
                    "Inchi": self.inchi,
                }
            ),
            authors=[],
            link=f"https://pubchem.ncbi.nlm.nih.gov/compound/{self.id}",
        )

    @staticmethod
    def create_expected(
        v: list[PubchemCompound] | AgentError,
    ) -> Expected[list[PubchemCompound], AgentError]:
        return Expected(list, AgentError, v)

    @staticmethod
    def create_single_expected(
        v: PubchemCompound | AgentError,
    ) -> Expected[PubchemCompound, AgentError]:
        return Expected(PubchemCompound, AgentError, v)


class PubchemQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count

    async def cid_to_data(
        self, client: httpx.AsyncClient, cid: str
    ) -> Expected[PubchemCompound, AgentError]:
        res = await client.get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/Title,IUPACName,MolecularFormula,MolecularWeight,Inchi/json"
        )
        if res.status_code > 299:
            return PubchemCompound.create_single_expected(AgentError(message=res.text))
        compound = json.loads(res.text)["PropertyTable"]["Properties"][0]
        return PubchemCompound.create_single_expected(
            PubchemCompound(
                id=str(compound["CID"]),
                molecular_formula=compound["MolecularFormula"],
                molecular_weight=compound["MolecularWeight"],
                inchi=compound["InChI"],
                iupac_name=compound["IUPACName"],
                name=compound["Title"],
            )
        )

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        cids: set[str] = set()
        for kw in kws:
            res = await client.get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{kw}/cids/json"
            )
            if res.status_code > 299:
                continue
            parsed_payload = json.loads(res.text)
            for cid in parsed_payload["IdentifierList"].get("CID", []):
                cids.add(str(cid))
        compounds = await asyncio.gather(
            *[self.cid_to_data(client, cid) for cid in cids]
        )
        compounds = [compound.value() for compound in compounds if compound.has_value()]
        return PublicationResult.create_expected(
            [compound.to_publication() for compound in compounds]
        )


class UniprotQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count

    async def query(
        self, client: httpx.AsyncClient, kws: list[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        results: list[PublicationResult] = []
        for kw in kws:
            res = await client.get(
                "https://rest.uniprot.org/uniprotkb/search",
                params={"query": kw, "size": self.res_count},
            )
            if res.status_code > 299:
                continue
            payload = json.loads(res.text)
            for res in payload["results"]:
                abstract = f"{res['proteinDescription']['recommendedName']['fullName']['value']}"
                for comment in res["comments"]:
                    if "texts" in "comments":
                        abstract = (
                            abstract
                            + f"{comment['commentType']}\n{comment['texts'][0]['value']}\n"
                        )
                results.append(
                    PublicationResult.model_validate(
                        {
                            "title": f"{res['primaryAccession']}.{res['uniProtkbId']}",
                            "source": "Uniprot",
                            "abstract": abstract,
                            "authors": [],
                            "link": f"https://uniprot.org/uniprotkb/${res['primaryAccession']}/entry",
                        }
                    )
                )
        return PublicationResult.create_expected(results)
