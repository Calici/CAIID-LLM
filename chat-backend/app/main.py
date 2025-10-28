from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.routes.agent import router as agent_router
from app.routes.fs import router as fs_router
from app.routes.server import router as server_router
from app.routes.workspace import router as workspace_router


app = FastAPI()

app.include_router(server_router)
app.include_router(workspace_router)
app.include_router(fs_router)
app.include_router(agent_router)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
