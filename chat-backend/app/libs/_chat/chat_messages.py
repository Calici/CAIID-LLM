from __future__ import annotations

from pydantic import TypeAdapter
from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from .utils import ProjectCompare, find_in_list
from .chat_message import (
    AIMessage,
    ChatMessage,
    StreamChatMessage,
    ToolCallCompleteMessage,
    ToolCallMessage,
    UserMessage,
)
import xml.etree.ElementTree as ET


class ChatMessages:
    messages: list[ChatMessage]

    def __init__(self, messages: list[ChatMessage]):
        self.messages = messages

    def user_chat(self, msg: str):
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
        last_message = self.messages[-1]
        if msg.type == "ai":
            return self.__ai_chat(msg, last_message)
        elif msg.type == "tool_call":
            return self.__tool_call_chat(msg, last_message)
        else:
            return self.__tool_call_done_chat(msg)

    def to_xml(self, amount: int = 2) -> str:
        filtered_messages: list[ChatMessage] = []
        for m in reversed(self.messages):
            if m.type == "ai" or m.type == "user":
                filtered_messages.append(m)
                if len(filtered_messages) == amount:
                    break
        root = ET.Element("chat_history")
        for m in reversed(filtered_messages):
            if m.type == "ai" or m.type == "user":
                element = ET.SubElement(root, "msg", role=m.type)
                element.text = m.content
        return ET.tostring(root).decode()

    def to_pydantic(self, exclude_last: bool = True) -> list[ModelMessage]:
        messages = [self.__to_message(m) for m in self.messages]
        messages = [m for m in messages if m is not None]
        if exclude_last:
            messages = messages[:-1]
        return messages

    def flatten(self) -> list[ChatMessage]:
        return self.messages

    @staticmethod
    def type_adapter():
        return TypeAdapter(list[ChatMessage])

    @staticmethod
    def from_json(v: str) -> ChatMessages:
        return ChatMessages(TypeAdapter(list[ChatMessage]).validate_json(v))

    @staticmethod
    def new(user_prompt: str) -> ChatMessages:
        return ChatMessages([UserMessage(content=user_prompt)])

    def __ai_chat(self, msg: AIMessage, last_message: ChatMessage) -> AIMessage:
        if last_message.type == "ai":
            last_message.content += msg.content
            return msg
        else:
            self.messages.append(msg)
            return msg

    def __tool_call_chat(
        self, msg: ToolCallMessage, last_message: ChatMessage
    ) -> ToolCallMessage:
        if (
            last_message.type == "tool_call"
            and msg.tool_call_id == last_message.tool_call_id
        ):
            self.messages[-1] = msg
        else:
            self.messages.append(msg)
        return msg

    def __tool_call_done_chat(self, msg: ToolCallCompleteMessage) -> ToolCallMessage:
        tool_call = find_in_list(
            self.messages,
            ProjectCompare[ChatMessage, str](
                lambda m: m.tool_call_id if m.type == "tool_call" else "",
                msg.tool_call_id,
            ),
        )
        assert tool_call is not None and tool_call[1].type == "tool_call"
        tool_call[1].is_complete = True
        return tool_call[1]

    @staticmethod
    def __to_message(msg: ChatMessage) -> ModelMessage | None:
        if msg.type == "ai":
            return ModelResponse(parts=[TextPart(msg.content)])
        elif msg.type == "user":
            return ModelRequest(parts=[UserPromptPart(msg.content)])
        else:
            return None
