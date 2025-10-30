from __future__ import annotations
import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
)
from pydantic.type_adapter import TypeAdapter
from pydantic_ai.agent import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from typing import Callable, Literal, Protocol, final, TypeVar

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.tools import Tool
from app.libs.drug_query import (
    ClinicalTrialsGov,
    EuropePMCQuery,
    PublicationQueryMaker,
    PublicationResult,
    PubmedQuery,
)
from app.libs.file_reader import file_reader
import xml.etree.ElementTree as ET
import asyncio
import pathlib


class UserMessage(BaseModel):
    type: Literal["user"] = "user"
    content: str


class AIMessage(BaseModel):
    type: Literal["ai"] = "ai"
    content: str


class ToolCallMessage(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    tool_id: str
    tool_call_id: str
    is_complete: bool


class ToolCallCompleteMessage(BaseModel):
    type: Literal["tool_call_end"] = "tool_call_end"
    tool_call_id: str


ChatMessage = UserMessage | AIMessage | ToolCallMessage
StreamChatMessage = AIMessage | ToolCallMessage | ToolCallCompleteMessage
CHAT_MESSAGE_ADAPTER = TypeAdapter(list[ChatMessage])

T = TypeVar("T")


def find_in_list(vs: list[T], f: Callable[[T], bool]) -> tuple[int, T] | None:
    for id, v in enumerate(vs):
        if f(v):
            return (id, v)
    return None


class ChatMessages:
    messages: list[ChatMessage]

    def __init__(self, messages: str | list[ChatMessage]):
        if isinstance(messages, list):
            assert len(messages) != 0
            self.messages = messages
        else:
            self.messages = [UserMessage(content=messages)]

    def chat(self, msg: str):
        if self.messages[-1].type == "user":
            self.messages[-1].content = msg
        else:
            self.messages.append(UserMessage(content=msg))

    def ai_chat(self, msg: StreamChatMessage) -> AIMessage | ToolCallMessage:
        """
        Writes a message into the message history, this function is meant for use inside
        a agentic stream loop to update the internal history. This will return the message
        part used to update the chat history.
        """
        if msg.type == "ai":
            last_message = self.messages[-1]
            if last_message.type == "ai":
                last_message.content += msg.content
                msg = last_message
            else:
                self.messages.append(msg)
            return msg
        elif msg.type == "tool_call":
            last_message = self.messages[-1]
            if (
                last_message.type == "tool_call"
                and msg.tool_call_id == last_message.tool_call_id
            ):
                self.messages[-1] = msg
            else:
                self.messages.append(msg)
            return msg
        elif msg.type == "tool_call_end":

            def searcher(v: ChatMessage):
                return v.type == "tool_call" and v.tool_call_id == msg.tool_call_id

            res = find_in_list(self.messages, searcher)
            assert res is not None
            id, message = res
            assert message.type == "tool_call"
            message.is_complete = True
            return message

    def to_xml(self, limit: int = 2):
        root = ET.Element("chat_history")
        filtered_messages = []
        for i in range(len(self.messages) - 1, -1, -1):
            filtered_messages.append(self.messages[i])
            if len(filtered_messages) == limit:
                break
        for m in reversed(filtered_messages):
            if m.type == "ai" or m.type == "user":
                element = ET.SubElement(root, "msg", role=m.type)
                element.text = m.content
        return ET.tostring(root).decode()

    def to_pydantic(self, exclude_last: bool = True) -> list[ModelMessage]:
        def to_message(msg: ChatMessage) -> ModelMessage | None:
            if msg.type == "ai":
                return ModelResponse(parts=[TextPart(msg.content)])
            elif msg.type == "user":
                return ModelRequest(parts=[UserPromptPart(msg.content)])

        messages = [to_message(m) for m in self.messages if to_message(m)]
        messages = [m for m in messages if m is not None]
        if exclude_last:
            messages = messages[:-1]
        return messages

    def to_json(self) -> str:
        return CHAT_MESSAGE_ADAPTER.dump_json(self.messages).decode("utf-8")

    def to_flat(self):
        return self.messages

    @staticmethod
    def from_json(v: str) -> ChatMessages:
        return ChatMessages(CHAT_MESSAGE_ADAPTER.validate_json(v))


class ChatFile(BaseModel):
    name: str
    summary: str
    path: str


class ChatStateDump(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    queries: list[PublicationResult]
    messages: list[ChatMessage]


class KeywordMaker(Protocol):
    async def get_keywords(self, messages: ChatMessages) -> list[str]: ...


class BlankKeywordMaker:
    async def get_keywords(self, messages: ChatMessages) -> list[str]:
        return []


class AgenticKeywordMaker:
    def __init__(self, agent: Agent):
        self.agent = agent

    def strip_ticks(self, msg: str) -> str:
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

    async def get_keywords(self, messages: ChatMessages) -> list[str]:
        chat_history = messages.to_xml()
        try:
            result = (await self.agent.run(chat_history)).output
            clean_result = self.strip_ticks(result)
            return TypeAdapter(list[str]).validate_json(clean_result)
        except ValidationError:
            return []


@final
class ChatState:
    queries: list[PublicationResult]
    files: list[ChatFile]
    messages: ChatMessages
    data_dir: pathlib.Path

    def __init__(
        self,
        messages: ChatMessages,
        data_dir: pathlib.Path,
        kw_maker: KeywordMaker = BlankKeywordMaker(),
        files: list[ChatFile] = [],
        queries: list[PublicationResult] = [],
    ):
        self.files = files
        self.messages = messages
        self.data_dir = data_dir
        self.queries = queries
        self.client = httpx.AsyncClient()
        self.pub_query_maker = PublicationQueryMaker(
            [PubmedQuery(), EuropePMCQuery(), ClinicalTrialsGov()]
        )
        self.kw_maker = kw_maker
        self.allow_query = True
        super().__init__()

    async def list_file(self):
        return self.files

    async def read_file(self, name: str):
        def same_name(f: ChatFile):
            return name == f.name

        file = find_in_list(self.files, same_name)
        if file is None:
            return "file not found"
        _, file = file
        file = await file_reader.read_file(self.data_dir / file.name)
        if not file.has_value():
            return f"FileReaderError: {file.error()}"
        return file.value()

    async def search_file(self, q: str):
        def in_summary(f: ChatFile):
            return q in f.summary

        file = find_in_list(self.files, in_summary)
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

    def get_agent(self, model: OpenAIChatModel, system_prompt: str) -> Agent:
        return Agent(
            model=model,
            tools=[
                Tool(
                    self.list_file,
                    name="ls",
                    description="List all files in the user filesystem",
                    strict=True,
                    max_retries=1,
                ),
                Tool(
                    self.read_file,
                    name="read_file",
                    description="Read a file in the current filesystem",
                    strict=True,
                    max_retries=1,
                ),
                Tool(
                    self.query_publications_length,
                    name="query_publications_length",
                    description="Get the length of the current obtained publications",
                    strict=True,
                    max_retries=1,
                ),
                Tool(
                    self.query_publications,
                    name="query_publications",
                    description="Queries publications, call get_publication to read the contents of queried publications.",
                    strict=True,
                    max_retries=1,
                ),
                Tool(
                    self.get_publications,
                    name="get_publications",
                    description=("Retrieve cached publication entries by index."),
                    strict=True,
                    max_retries=1,
                ),
            ],
            system_prompt=system_prompt,
        )

    def to_json(self) -> str:
        return ChatStateDump(
            queries=self.queries, messages=self.messages.messages
        ).model_dump_json()

    def to_dump(self) -> ChatStateDump:
        return ChatStateDump(queries=self.queries, messages=self.messages.messages)

    @staticmethod
    def from_file(
        p: pathlib.Path,
        data_dir: pathlib.Path,
        files: list[ChatFile],
        kw_maker: KeywordMaker = BlankKeywordMaker(),
    ) -> ChatState:
        with open(p, "r") as f:
            dump_state = ChatStateDump.model_validate_json(f.read())
        return ChatState(
            ChatMessages(dump_state.messages),
            data_dir,
            kw_maker,
            files,
            dump_state.queries,
        )
