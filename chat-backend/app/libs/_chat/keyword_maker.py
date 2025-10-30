from asyncio import Protocol
from typing import final

from pydantic import TypeAdapter, ValidationError
from pydantic_ai import Agent

from .chat_messages import ChatMessages


class KeywordMaker(Protocol):
    async def get_keywords(self, msgs: ChatMessages) -> list[str]: ...


@final
class BlankKeywordMaker:
    async def get_keywords(self, msgs: ChatMessages) -> list[str]:
        return []


@final
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

    async def get_keywords(self, msgs: ChatMessages) -> list[str]:
        chat_history = msgs.to_xml()
        try:
            result = (await self.agent.run(chat_history)).output
            clean_result = self.strip_ticks(result)
            return TypeAdapter(list[str]).validate_json(clean_result)
        except ValidationError:
            return []
