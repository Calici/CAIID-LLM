from __future__ import annotations
from pydantic import BaseModel, ValidationError
from typing import Protocol, final
from app.libs.expected import Expected
import xml.etree.ElementTree as ET
import httpx
import logging
import json


class AgentError(BaseModel):
    """Container for agent-related error information."""

    message: str


class PublicationResult(BaseModel):
    title: str
    source: str
    abstract: str | None
    authors: list[str]
    doi: str | None

    @staticmethod
    def create_expected(
        value: list[PublicationResult] | AgentError,
    ) -> Expected[list["PublicationResult"], AgentError]:
        return Expected(list, AgentError, value)

    async def resolve_doi(self, client: httpx.AsyncClient) -> str | None:
        if self.doi is not None:
            res = await client.get(
                f"https://dx.doi.org/{self.doi}", follow_redirects=False
            )
            return res.headers.get("LOCATION")
        return None

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
        pdf_link = await self.resolve_doi(client)
        if pdf_link is not None:
            root.append(create_elem("link", text=pdf_link))
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
            try:
                summaries.append(
                    PublicationResult.model_validate(
                        {
                            "pub_date": pub_date,
                            "title": title.text if title is not None else None,
                            "authors": authors,
                            "doi": doi.text if doi is not None else None,
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
            try:
                publications.append(
                    PublicationResult.model_validate(
                        {
                            "title": record.get("title"),
                            "abstract": record.get("abstractText"),
                            "source": self.source,
                            "authors": record.get("authorString", "").split(","),
                            "pub_date": record.get("firstPublicationDate", ""),
                            "doi": record.get("doi"),
                        }
                    )
                )
            except ValidationError as exc:
                logging.error(f"EuropePMCQuery: {exc}")
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
