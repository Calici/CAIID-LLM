"""Agent and messaging protocol definitions."""

from __future__ import annotations
from collections import deque
from collections.abc import Iterable, Iterator
from pathlib import Path
from collections.abc import Sequence
from typing import Literal, Protocol, final, override
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai import Agent
from ddgs import DDGS
import xml.etree.ElementTree as ET
from threading import Thread
import asyncio
import httpx
import json
import logging
from app.libs.expected import Expected


# Utility Function
def strip_ticks(msg: str) -> str:
    msg_beg = msg.find("```")
    if msg_beg == -1:
        return msg
    tick_end = msg.find("\n", msg_beg + 3)
    if tick_end == -1:
        return ""
    msg_end = msg.find("```", tick_end + 1)
    if msg_end == -1:
        return msg
    msg = msg[tick_end:msg_end]
    return msg.strip()


class AgentError(BaseModel):
    """Container for agent-related error information."""

    message: str


class KeywordQuery(Protocol):
    """Protocol for components that return related keywords for a query."""

    async def query(self, keywords: Iterable[str]) -> list[str] | AgentError:
        """Return related keywords or an error for the given keyword set."""
        ...


class Message(BaseModel):
    """Conversation message with a role and body."""

    role: Literal["user", "ai", "sys"]
    msg: str


class Messages:
    """Fixed-size FIFO buffer for conversation messages."""

    def __init__(self, max_size: int) -> None:
        assert max_size > 0, "max_size must be greater than zero"
        self.__messages: deque[Message] = deque(maxlen=max_size)

    def append_message(self, message: Message) -> None:
        """Add a message to the buffer, discarding the oldest if full."""

        self.__messages.append(message)

    def to_list(self) -> list[Message]:
        return [msg for msg in self.__messages]

    def to_xml(self, cutoff: int | None = None) -> str:
        root = ET.Element("ChatHistory")
        cutoff = cutoff if cutoff is not None else len(self)
        cutoff = min(cutoff, len(self))
        cutoff_beg = max(0, len(self) - cutoff)
        for i in range(cutoff_beg, cutoff):
            msg = self.__messages[i]
            e = ET.SubElement(root, "Message", role=msg.role)
            e.text = msg.msg
        return ET.tostring(root).decode()

    @property
    def size(self) -> int:
        """Current number of buffered messages."""

        return len(self.__messages)

    def __len__(self) -> int:
        return len(self.__messages)

    def __iter__(self) -> Iterator[Message]:
        return iter(self.__messages)

    @override
    def __repr__(self) -> str:
        return self.to_xml()


class KeywordAgent(Protocol):
    """Protocol for generating keyword seeds from a message and history."""

    async def generate(self, history: Messages) -> list[str] | AgentError: ...


class ContextAgent(Protocol):
    """Protocol that produces a textual context for a message."""

    async def build(self, history: Messages) -> str | AgentError: ...


class FileToString(Protocol):
    """Convert a filesystem path into a string representation."""

    async def convert(self, path: Path) -> str | AgentError: ...


@final
class SummaryAgent:
    """Protocol for agents producing named summaries for files."""

    def __init__(self, model: OpenAIChatModel, prompt: str, retry_count: int = 3):
        self.agent = Agent(model, system_prompt=prompt)
        self.retry_count = retry_count

    async def summarise(
        self, content: str, retry_count: int | None = None
    ) -> str | AgentError:
        if retry_count is None:
            retry_count = self.retry_count
        res = await self.agent.run(content)
        return res.output


@final
class TemplatedKeywordAgent:
    def __init__(
        self,
        prompt: str,
        model: OpenAIChatModel,
        chat_cutoff: int = 2,
        retry_count: int = 3,
    ):
        self.agent = Agent(model, system_prompt=prompt)
        self.retry_count = retry_count
        self.chat_cutoff = chat_cutoff

    async def generate_with_xml(
        self, msg: str, retry_count: int | None = None
    ) -> list[str] | AgentError:
        validator = TypeAdapter(list[str])
        retry_count = self.retry_count if retry_count is None else retry_count
        try:
            response = await self.agent.run(msg)
            formatted_response = strip_ticks(response.output)
            return validator.validate_json(formatted_response)
        except Exception as e:
            retry_count -= 1
            if retry_count == 0:
                return AgentError(message=str(e))
            else:
                return await self.generate_with_xml(msg, retry_count)

    async def generate(self, history: Messages) -> list[str] | AgentError:
        return await self.generate_with_xml(
            history.to_xml(self.chat_cutoff), self.retry_count
        )

    @staticmethod
    def load_system_prompt(
        p: Path, model: OpenAIChatModel, kw_count: int = 3, retry_count: int = 3
    ) -> TemplatedKeywordAgent:
        with open(p, "r") as f:
            return TemplatedKeywordAgent(
                f.read().format(keyword_count=kw_count), model, retry_count
            )


class DDGSTextQueryResult(BaseModel):
    title: str
    href: str
    body: str

    def to_xml(self) -> str:
        root = ET.Element("DuckDuckGo")
        root.append(ET.Element("Title", text=self.title))
        root.append(ET.Element("Href", text=self.href))
        root.append(ET.Element("Body", text=self.body))
        return ET.tostring(root).decode()


@final
class DDGSQuery:
    def __init__(self, result_count: int = 10):
        self.ddgs = DDGS()
        self.result_count = result_count

    def run_ddgs_query(self, kw: str) -> list[str] | AgentError:
        try:
            results = self.ddgs.text(query=kw, max_results=self.result_count)
            results = [DDGSTextQueryResult.model_validate(result) for result in results]
            return [res.to_xml() for res in results]
        except Exception as e:
                return AgentError(message=str(e))

    async def arun_ddgs_query(self, kw: str) -> list[str] | AgentError:
        ref: dict[str, list[str] | AgentError] = {"val": []}

        def assign_func():
            ref["val"] = self.run_ddgs_query(kw)

        t = Thread(target=assign_func)
        t.start()
        t.join()
        return ref["val"]

    async def query(self, kws: Sequence[str]) -> list[str] | AgentError:
        query_result = await asyncio.gather(*[self.arun_ddgs_query(kw) for kw in kws])
        results: list[str] = []
        for id, res in enumerate(query_result):
            if isinstance(res, AgentError):
                return AgentError(message=f"{id}: {res.message}")
            results.append("\n".join(res))
        return results


class PublicationResult(BaseModel):
    title: str
    source: str
    abstract: str | None
    authors: list[str]
    doi: str | None

    @staticmethod
    def create_expected(
        value: list["PublicationResult"] | AgentError,
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
        root = ET.Element("Publication", src=self.source, title=self.title)

        def create_elem(tag: str, text: str) -> ET.Element:
            elm = ET.Element(tag)
            elm.text = text
            return elm

        if self.abstract is not None:
            root.append(create_elem("Abstract", text=self.abstract))
        authors = ET.Element("Authorlist")
        for author in self.authors:
            authors.append(create_elem("Author", text=author))
        root.append(authors)
        pdf_link = await self.resolve_doi(client)
        if pdf_link is not None:
            root.append(create_elem("Link", text=pdf_link))
        return ET.tostring(root).decode()


class PublicationQuery(Protocol):
    async def query(
        self, client: httpx.AsyncClient, kws: Sequence[str]
    ) -> Expected[list[PublicationResult], AgentError]: ...


@final
class PubmedQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count
        self.source = "Pubmed"

    async def query_content(
        self, client: httpx.AsyncClient, ids: Sequence[str]
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
        self, client: httpx.AsyncClient, kws: Sequence[str]
    ) -> Expected[list[PublicationResult], AgentError]:
        res = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "term": " AND ".join([kw.replace(" ", "+") for kw in kws]),
                "retmax": str(self.res_count),
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
        self, client: httpx.AsyncClient, kws: Sequence[str]
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
        self, client: httpx.AsyncClient, kws: Sequence[str]
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
class ClinicalTrialsQuery:
    def __init__(self, res_count: int = 5):
        self.res_count = res_count


@final
class PublicationQueryAdapter:
    def __init__(self, qs: Sequence[PublicationQuery]):
        self.client = httpx.AsyncClient()
        self.qs = qs

    def find_similar(
        self, cur_publications: list[PublicationResult], publication: PublicationResult
    ) -> bool:
        for p in cur_publications:
            if p.title == publication.title and p.doi is None:
                p.doi = publication.doi
                return True
        return False

    async def query(self, kws: Sequence[str]) -> list[str] | AgentError:
        res = await asyncio.gather(*[q.query(self.client, kws) for q in self.qs])
        publications: list[PublicationResult] = []
        for r in res:
            if not r.has_value():
                logging.error(r.error())
                continue
            publications.extend(
                [
                    publication
                    for publication in r.value()
                    if not self.find_similar(publications, publication)
                ]
            )
        parsed_publications = await asyncio.gather(
            *[p.to_xml(self.client) for p in publications]
        )
        return parsed_publications
