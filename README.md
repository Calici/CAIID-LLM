# Mindblowing LLM

A small full-stack playground for experimenting with local large language model deployments and their supporting services.

## Repository Layout
- `chat-backend/` – FastAPI service that exposes an HTML endpoint and wires pydantic-ai agents against an OpenAI-compatible provider configured via environment variables.
- `chat-frontend/` – Next.js 13 App Router UI that pings the backend and renders responses through a simple button-driven demo.
- `llama-cpp/` – Git submodule pointing to `ggerganov/llama.cpp`, used to compile the standalone inference server with CUDA acceleration.

Supporting files in the root directory:
- `docker-compose.yml` – Spins up Postgres, the backend API, the Next.js frontend, and the compiled `llama-server` container in one command.
- `dockerfile.llama` – Multi-stage build that compiles and packages `llama.cpp` with CUDA for the runtime service referenced in `docker-compose.yml`.

## Quick Start
- Install submodule dependencies: `git submodule update --init --recursive`.
- Launch the full stack: `docker compose up --build` (Docker with NVIDIA support required for the llama server stage).
- Visit `http://localhost:3000` to hit the frontend, which calls the backend at `http://localhost:8000`.

## Configuration Notes
- The backend reads `OPENAI_API_KEY`, `OPENAI_API_PROVIDER`, and `OPENAI_API_MODEL` from the environment (see `chat-backend/app/config.py`).
- The frontend expects `NEXT_PUBLIC_BACKEND_URL` to point at the backend base URL; it defaults to `http://localhost:8000` for local development.
