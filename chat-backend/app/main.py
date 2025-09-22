from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

_HTML_BODY = "<h1> HELLO WORLD </h1>"

@app.api_route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"], response_class=HTMLResponse)
async def root() -> str:
    return _HTML_BODY


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"], response_class=HTMLResponse)
async def catch_all(path: str) -> str:
    return _HTML_BODY
