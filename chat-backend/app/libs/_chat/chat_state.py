from __future__ import annotations

import asyncio
import pathlib
from typing import final

import httpx
from pydantic import BaseModel, ValidationError

from app.libs.drug_query import (
    ChemblQuery,
    ClinicalTrialsGov,
    EuropePMCQuery,
    OpenFDAQuery,
    PubchemQuery,
    PublicationQuery,
    PublicationQueryMaker,
    PublicationResult,
    PubmedQuery,
    UniprotQuery,
)
from app.libs.file_reader import file_reader

from .chat_message import ChatMessage
from .chat_messages import ChatMessages
from .keyword_maker import BlankKeywordMaker, KeywordMaker
from .utils import ProjectCompare, find_in_list


class ChatFile(BaseModel):
    name: str
    summary: str
    path: str


class FlatChatState(BaseModel):
    messages: list[ChatMessage]
    queries: list[PublicationResult]


@final
class ChatState:
    def __init__(
        self,
        messages: ChatMessages,
        data_dir: pathlib.Path,
        kw_maker: KeywordMaker,
        files: list[ChatFile],
        queries: list[PublicationResult],
        additional_providers: list[PublicationQuery] = [],
    ):
        self.files = files
        self.messages = messages
        self.data_dir = data_dir
        self.queries = queries
        self.client = httpx.AsyncClient()
        self.pub_query_maker = PublicationQueryMaker(
            [
                PubmedQuery(),
                EuropePMCQuery(),
                ClinicalTrialsGov(),
                ChemblQuery(),
            ]
        )
        self.drug_query_maker = PublicationQueryMaker(
            [OpenFDAQuery(), PubchemQuery(), UniprotQuery(), *additional_providers]
        )
        self.kw_maker = kw_maker
        self.allow_query = True

    def append_drug_query(self, q: PublicationQuery):
        self.drug_query_maker.qs.append(q)

    async def list_file(self):
        return self.files

    async def read_file(self, name: str) -> str:
        file = find_in_list(
            self.files, ProjectCompare[ChatFile, str](lambda p: p.name, name)
        )
        if file is None:
            return "file not found"
        _, file = file
        file = await file_reader.read_file(self.data_dir / file.name)
        if not file.has_value():
            return f"FileReaderError: {file.error()}"
        return file.value()

    async def search_file(self, q: str):
        file = find_in_list(
            self.files,
            ProjectCompare[ChatFile, str](lambda p: p.summary, q),
        )
        if file is None:
            return "file not found"
        _, file = file
        return file.name

    async def get_publications(self, indices: list[int] | None):
        if indices is None or len(indices) == 0:
            indices = list(range(len(self.queries)))
        return "\n".join(
            await asyncio.gather(
                *[
                    self.queries[i].to_xml(self.client)
                    for i in indices
                    if i >= 0 and i < len(self.queries)
                ]
            )
        )

    async def query_drugs(self):
        if not self.allow_query:
            return (
                f"Found {len(self.queries)}. Call get_publications to retrieve entries"
            )
        self.allow_query = False
        kws = await self.kw_maker.get_keywords(self.messages)
        if len(kws) == 0:
            return "No keywords. Be more specific"
        res = await self.drug_query_maker.query(kws)
        if res.has_value():
            self.queries = res.value()
            return (
                f"Found {len(self.queries)}. Call get_publications to retrieve entries"
            )
        return "failure"

    async def query_publications(self):
        if not self.allow_query:
            return (
                f"Found {len(self.queries)}. Call get_publications to retrieve entries"
            )
        self.allow_query = False
        kws = await self.kw_maker.get_keywords(self.messages)
        if len(kws) == 0:
            return "No keywords. Be more specific"
        res = await self.pub_query_maker.query(kws)
        if res.has_value():
            self.queries = res.value()
            return (
                f"Found {len(self.queries)}. Call get_publications to retrieve entries"
            )
        return "failure"

    async def query_publications_length(self):
        return len(self.queries)

    def flatten(self) -> FlatChatState:
        return FlatChatState(messages=self.messages.flatten(), queries=self.queries)

    @staticmethod
    def from_flat(
        flat: FlatChatState,
        data_dir: pathlib.Path,
        kw_maker: KeywordMaker,
        files: list[ChatFile],
    ) -> ChatState:
        return ChatState(
            ChatMessages(flat.messages), data_dir, kw_maker, files, flat.queries
        )

    @staticmethod
    def new(
        user_prompt: str,
        data_dir: pathlib.Path,
        kw_maker: KeywordMaker = BlankKeywordMaker(),
        files: list[ChatFile] = [],
    ):
        return ChatState(ChatMessages.new(user_prompt), data_dir, kw_maker, files, [])

    @staticmethod
    def save(save_path: pathlib.Path, state: ChatState):
        with open(save_path, "w") as f:
            _ = f.write(state.flatten().model_dump_json())

    @staticmethod
    def load(
        save_path: pathlib.Path,
        data_dir: pathlib.Path,
        kw_maker: KeywordMaker = BlankKeywordMaker(),
        files: list[ChatFile] = [],
    ) -> ChatState:
        with open(save_path, "r") as f:
            try:
                flat_state = FlatChatState.model_validate_json(f.read())
                return ChatState.from_flat(flat_state, data_dir, kw_maker, files)
            except ValidationError:
                return ChatState.new(
                    "Hi. What is your name ?", data_dir, kw_maker, files
                )
