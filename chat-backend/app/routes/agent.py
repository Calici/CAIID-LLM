from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic_ai.agent import Agent
from app.libs.expected import Expected
from app.config import settings, ConfigError
from app.db import WorkspaceSchema, TempFilesSchema
from app.libs.file_reader import file_reader


router = APIRouter()


async def run_agent(agent: Agent, content: str) -> Expected[str, ConfigError]:
    try:
        return Expected(str, ConfigError, (await agent.run(content)).output)
    except Exception as e:
        return Expected(str, ConfigError, ConfigError(str(e)))


async def create_topic_from_prompt(user_input: str):
    return (
        await settings.get_topic_agent().aand_then(
            str, lambda agent: run_agent(agent, user_input)
        )
    ).transform(str, lambda x: "".join([i for i in x if x not in ["'", "`", '"']]))


async def create_file_summary(content: str):
    return await settings.get_summary_agent().aand_then(
        str, lambda agent: run_agent(agent, content)
    )


@router.get("/agent.topic_maker/{workspace_uuid}")
async def topic_maker(workspace_uuid: str) -> str:
    with settings.get_db_conn() as conn:
        record = WorkspaceSchema.get_by_uuid(conn, workspace_uuid)
    if record is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    chat_state = record.load_state(settings.chat_dir(), settings.data_path(), [])
    history_xml = chat_state.messages.to_xml()
    topic = await create_topic_from_prompt(history_xml)
    if not topic.has_value():
        raise HTTPException(status_code=412, detail=str(topic.error()))
    return topic.value()


@router.get("/agent.summarise_file/{temp_file_uuid}")
async def summarise_file(temp_file_uuid: str) -> str:
    with settings.get_db_conn() as conn:
        record = TempFilesSchema.get_by_uuid(conn, temp_file_uuid)
    if record is None:
        raise HTTPException(status_code=404, detail="Temporary file not found")

    tmp_file_path = settings.tmp_path() / record.name
    if not tmp_file_path.is_file():
        raise HTTPException(status_code=404, detail="Temporary file not found")
    content = await file_reader.read_file(tmp_file_path)
    if not content.has_value():
        raise HTTPException(status_code=500, detail=str(content.error()))
    summary = await create_file_summary(content.value())
    if not summary.has_value():
        raise HTTPException(status_code=412, detail=str(summary.error()))
    return summary.value()
