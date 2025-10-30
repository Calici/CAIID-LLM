from pydantic import BaseModel
from typing import Literal


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


# Declaration for commonly used unions
ChatMessage = UserMessage | AIMessage | ToolCallMessage
StreamChatMessage = AIMessage | ToolCallMessage | ToolCallCompleteMessage
