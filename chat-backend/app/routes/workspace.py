from __future__ import annotations
from collections.abc import AsyncIterable
from typing import Literal
from typing_extensions import Annotated
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, AfterValidator
from pydantic_ai.agent import Agent
from app.config import settings
from app.db import WorkspaceSchema
from app.libs._chat.chat_message import (
    AIMessage,
    ToolCallCompleteMessage,
    ToolCallMessage,
)
from app.libs._chat import BlankKeywordMaker, ChatMessages, ChatState, FlatChatState
from app.libs.drug_query import PublicationResult
from app.routes.agent import create_topic_from_prompt


def _trim_check_blank(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("value must be non-empty after trimming")
    return trimmed


class WorkspaceRenamePayload(BaseModel):
    name: Annotated[str, AfterValidator(_trim_check_blank)]


class WorkspaceChatPayload(BaseModel):
    user_prompt: Annotated[str, AfterValidator(_trim_check_blank)]


router = APIRouter()


@router.get("/workspace.summary")
async def list_workspaces():
    with settings.get_db_conn() as conn:
        records = WorkspaceSchema.all(conn)
    return [
        {
            "name": workspace.name,
            "uuid": str(workspace.uuid),
        }
        for workspace in records
    ]


@router.post("/workspace.rename/{uuid}")
async def rename_workspace(uuid: str, payload: WorkspaceRenamePayload):
    with settings.get_db_conn() as conn:
        record = WorkspaceSchema.get_by_uuid(conn, uuid)
        if record is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        record.name = payload.name
        _ = conn.run_query(record.update_sql())
    return record


class SerializedWorkspace(BaseModel):
    name: str
    uuid: str
    last_modified: str
    create_date: str
    chat_history: FlatChatState


def serialize_workspace(record: WorkspaceSchema):
    state = ChatState.load(
        record.chat_path(settings.chat_dir()), settings.data_path(), BlankKeywordMaker()
    )
    return SerializedWorkspace(
        name=record.name,
        uuid=str(record.uuid),
        last_modified=record.last_modified.isoformat(),
        create_date=record.create_date.isoformat(),
        chat_history=state.flatten(),
    )


@router.get("/workspace/{uuid}")
async def get_workspace(uuid: str):
    with settings.get_db_conn() as conn:
        record = WorkspaceSchema.get_by_uuid(conn, uuid)
    if record is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return serialize_workspace(record)


class ChatPayload(BaseModel):
    type: Literal["chat"] = "chat"
    content: AIMessage | ToolCallMessage


class RecordPayload(BaseModel):
    type: Literal["record"] = "record"
    content: SerializedWorkspace


class QueryPayload(BaseModel):
    type: Literal["query"] = "query"
    content: list[PublicationResult]


class ErrorPayload(BaseModel):
    type: Literal["error"] = "error"
    content: str


async def chat_streamer(
    user_message: str,
    agent: Agent,
    workspace: WorkspaceSchema,
    chat_state: ChatState,
    is_new: bool,
) -> AsyncIterable[ChatPayload | RecordPayload | QueryPayload]:
    if is_new:
        yield RecordPayload(content=serialize_workspace(workspace))
    query_sent_before = False
    async for ev in agent.run_stream_events(
        user_message, message_history=chat_state.messages.to_pydantic()
    ):
        if ev.event_kind == "part_start" and ev.part.part_kind == "text":
            message = AIMessage(content=ev.part.content)
            _ = chat_state.messages.ai_chat(message)
            yield ChatPayload(content=message)
        elif ev.event_kind == "part_delta" and ev.delta.part_delta_kind == "text":
            message = AIMessage(content=ev.delta.content_delta)
            _ = chat_state.messages.ai_chat(message)
            yield ChatPayload(content=message)
        elif ev.event_kind == "function_tool_call":
            message = chat_state.messages.ai_chat(
                ToolCallMessage(
                    tool_name=f"{ev.part.tool_name}({', '.join([str(v) for v in ev.part.args_as_dict().values()])})",
                    tool_id=ev.part.tool_name,
                    tool_call_id=ev.part.tool_call_id,
                    is_complete=False,
                )
            )
            yield ChatPayload(content=message)
        elif ev.event_kind == "function_tool_result":
            message = chat_state.messages.ai_chat(
                ToolCallCompleteMessage(
                    tool_call_id=ev.tool_call_id,
                )
            )
            # query is done somehow
            if not chat_state.allow_query and not query_sent_before:
                yield QueryPayload(content=chat_state.queries)
                query_sent_before = True
            yield ChatPayload(content=message)
    ChatState.save(workspace.chat_path(settings.chat_dir()), chat_state)


async def chat_serializer(
    coro: AsyncIterable[ChatPayload | RecordPayload | QueryPayload],
) -> AsyncIterable[str]:
    try:
        async for e in coro:
            yield f"{e.model_dump_json()}\n"
    except Exception as e:
        yield f"{ErrorPayload(content=f'{type(e)}: {str(e)}').model_dump_json()}\n"


class WorkspaceChatPayload(BaseModel):
    user_prompt: str
    uuid: str | None = None


@router.post("/workspace.chat")
async def chat_with_ai(payload: WorkspaceChatPayload):
    # This part creates or queries the workspace
    kw_maker = settings.get_keyword_maker()
    if not kw_maker.has_value():
        raise HTTPException(status_code=412, detail="workspace chat")
    with settings.get_db_conn() as conn:
        if payload.uuid is not None:
            is_new = False
            record = WorkspaceSchema.get_by_uuid(conn, payload.uuid)
            if record is None:
                raise HTTPException(status_code=404, detail="workspace not found")
            chat_state = ChatState.load(
                record.chat_path(settings.chat_dir()),
                settings.data_path(),
                kw_maker.value(),
                settings.get_files(),
            )
            chat_state.messages.user_chat(payload.user_prompt)
            ChatState.save(record.chat_path(settings.chat_dir()), chat_state)
        else:
            is_new = True
            name = await create_topic_from_prompt(
                ChatMessages.new(payload.user_prompt).to_xml()
            )
            if not name.has_value():
                raise HTTPException(
                    status_code=412, detail=f"name agent: {str(name.error())}"
                )
            record = WorkspaceSchema.create(name=name.value().strip())
            _ = conn.run_query(record.insert_sql())
            chat_state = ChatState.new(
                payload.user_prompt,
                settings.data_path(),
                kw_maker.value(),
                settings.get_files(),
            )
            ChatState.save(record.chat_path(settings.chat_dir()), chat_state)
    # Let's
    agent = settings.get_chat_agent(chat_state)
    if not agent.has_value():
        raise HTTPException(status_code=412, detail="workspace chat")
    return StreamingResponse(
        chat_serializer(
            chat_streamer(
                payload.user_prompt, agent.value(), record, chat_state, is_new
            )
        )
    )


@router.delete("/workspace/{uuid}")
async def delete_workspace(uuid: str):
    with settings.get_db_conn() as conn:
        record = WorkspaceSchema.get_by_uuid(conn, uuid)
        if record is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        _ = conn.run_query(record.delete_sql())
        record.chat_path(settings.chat_dir()).unlink(missing_ok=True)
    return {"status": "deleted"}
