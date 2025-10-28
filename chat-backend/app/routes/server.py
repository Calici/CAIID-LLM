from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings


router = APIRouter()


@router.get("/server")
async def get_server() -> dict[str, str | None]:
    with settings.get_db_conn() as conn:
        return {
            "name": settings.config.get_value("SERVER_NAME", conn),
            "model_name": settings.config.get_value("MODEL_NAME", conn),
            "api_url": settings.config.get_value("API_URL", conn),
        }


class ServerUpdatePayload(BaseModel):
    name: str
    model_name: str
    api_url: str
    api_key: str


@router.post("/server.update")
async def update_server(d: ServerUpdatePayload) -> None:
    with settings.get_db_conn() as conn:
        settings.config.set_value("SERVER_NAME", d.name, conn)
        settings.config.set_value("MODEL_NAME", d.model_name, conn)
        settings.config.set_value("API_URL", d.api_url, conn)
        settings.config.set_value("API_KEY", d.api_key, conn)
