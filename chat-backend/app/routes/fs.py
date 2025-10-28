from __future__ import annotations
from fastapi import APIRouter, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, AfterValidator
from typing_extensions import Annotated

from app.config import settings
from app.db import TempFilesSchema, FilesSchema
import shutil


router = APIRouter()


def _trim_check_blank(value: str) -> str:
    trimmed = value.strip()
    if len(trimmed) == 0:
        raise ValueError("value must be non-empty after trimming")
    return trimmed


class TempUploadPayload(BaseModel):
    name: Annotated[str, AfterValidator(_trim_check_blank)]
    file: UploadFile
    summary: str | None = None


@router.post("/fs.temp_upload")
async def temp_upload(payload: Annotated[TempUploadPayload, Form()]):
    save_path = settings.tmp_path() / payload.name
    with settings.get_db_conn() as get_db_conn:
        temp_record = TempFilesSchema.get_by_name(get_db_conn, payload.name)
        if temp_record is not None:
            raise HTTPException(status_code=409, detail="file exists")
        temp_record = TempFilesSchema.create(
            name=save_path.name, extension=save_path.suffix
        )
        _ = get_db_conn.run_query(temp_record.insert_sql())
    with open(save_path, "wb") as f:
        _ = f.write(await payload.file.read())
    return {"uuid": str(temp_record.uuid)}


class ConfirmUploadPayload(BaseModel):
    name: Annotated[str, AfterValidator(_trim_check_blank)]
    summary: Annotated[str, AfterValidator(_trim_check_blank)]


@router.post("/fs.confirm_upload/{temp_file_uuid}")
async def confirm_upload(temp_file_uuid: str, payload: ConfirmUploadPayload):
    with settings.get_db_conn() as get_db_conn:
        temp_record = TempFilesSchema.get_by_uuid(get_db_conn, temp_file_uuid)
        if temp_record is None:
            raise HTTPException(status_code=404, detail="temp_files not found")
        cur_record = FilesSchema.get_by_name(get_db_conn, temp_record.name)
        if cur_record is not None:
            raise HTTPException(status_code=409, detail="file exists. change name ?")
        record = FilesSchema.create(name=payload.name, summary=payload.summary)
        _ = get_db_conn.run_query(record.insert_sql())
        _ = shutil.move(
            settings.tmp_path() / temp_record.name, settings.data_path() / record.name
        )
        _ = get_db_conn.run_query(temp_record.delete_sql())
    return {
        "name": record.name,
        "summary": record.summary,
        "uuid": str(record.uuid),
        "create_date": record.create_date.isoformat(),
        "last_modified": record.last_modified.isoformat(),
    }


@router.get("/fs.ls")
async def list_files() -> list[dict[str, str]]:
    with settings.get_db_conn() as get_db_conn:
        records = FilesSchema.all(get_db_conn)
    return [
        {
            "name": record.name,
            "summary": record.summary,
            "uuid": str(record.uuid),
        }
        for record in records
    ]


@router.get("/fs.download_file/{file_uuid}")
async def download_file(file_uuid: str):
    with settings.get_db_conn() as get_db_conn:
        record = FilesSchema.get_by_uuid(get_db_conn, file_uuid)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")
    target_path = settings.data_path() / record.name
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        path=str(target_path),
        filename=record.name,
        media_type="application/octet-stream",
    )


@router.delete("/fs/{file_uuid}")
async def delete_file(file_uuid: str):
    with settings.get_db_conn() as get_db_conn:
        record = FilesSchema.get_by_uuid(get_db_conn, file_uuid)
        if record is None:
            raise HTTPException(status_code=404, detail="file not found")
        target_path = settings.data_path() / record.name
        if target_path.exists():
            if target_path.is_file():
                target_path.unlink()
            else:
                shutil.rmtree(target_path)
        _ = get_db_conn.run_query(record.delete_sql())

    return {"status": "deleted"}
