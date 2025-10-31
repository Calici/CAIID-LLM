# Drug Researcher

Drug Researcher bundles a FastAPI backend, a Next.js interface, and an optional local LLM runtime into one Docker-driven workspace. This README walks through the knobs exposed in `docker-compose.yml`, explains where data lands, and shows how to launch the Lite and Heavy stacks.

## Prerequisites
- Docker 24+ with Compose v2
- Optional: NVIDIA container runtime for the Heavy mode (GPU-accelerated LLaMA server)
- Clone the repository with submodules: `git clone https://github.com/Calici/caiid-llm --recurse-submodules`

## Lite Mode Quickstart
1. From the project root, export any required secrets for the backend—for example `export OPENAI_API_KEY=sk-...`.
2. (Optional) Create a `.env` file to override ports or storage paths, then save it alongside `docker-compose.yml`.
3. Build and start the frontend and backend only:  
   `docker compose up --build chat-backend chat-frontend`
4. Open `http://localhost:3000` in your browser and wait for API responses from `http://localhost:8000`.
5. When finished, stop the stack with `Ctrl+C` and clean up containers using `docker compose down`.

## Environment & Port Overrides

All overrides shown below can be applied inline (e.g. `APP_DB_PATH=/mnt/prod.db docker compose up`) or by creating a `.env` file in the repository root. `docker-compose.yml` already references these variables, so Compose swaps in your values automatically.

### `chat-backend` service
- **Environment**: Set `APP_DB_PATH`, `APP_DATA_PATH`, and `APP_ASSETS_PATH` to keep SQLite and generated files under a different mount. Example `.env` snippet:  
  ```
  APP_DB_PATH=/data/prod.db
  APP_DATA_PATH=/data
  APP_ASSETS_PATH=/assets
  ```
  Start the service with `docker compose up chat-backend` and the backend will read the new paths.
- **Ports**: Change the host binding to avoid collisions. Either edit the compose file to `- "18000:8000"` or export `CHAT_BACKEND_PORT=18000` and adjust the entry to `- "${CHAT_BACKEND_PORT:-8000}:8000"` for a configurable host port.

### `chat-frontend` service
- **Environment**: Override `NEXT_PUBLIC_API_URL` to point the UI at a remote backend:  
  ```
  NEXT_PUBLIC_API_URL=https://api.example.com
  ```
  Rebuild with `docker compose up --build chat-frontend` so Next.js picks up the new value.
- **Ports**: Rebind the UI with `FRONTEND_PORT=3300 docker compose up chat-frontend` after updating the compose entry to `- "${FRONTEND_PORT:-3000}:3000"`. This keeps the container on port 3000 while exposing it on an alternate host port.

### `llama` service
- **Environment**: Every `LLAMA_ARG_*` entry becomes a CLI flag. To move the HTTP server to 8181 and load a different model, set:  
  ```
  LLAMA_ARG_PORT=8181
  LLAMA_ARG_MODEL=/llm-models/llama-3-8b.gguf
  ```
  Update the volume mapping so the model path exists, then run `docker compose up llama`.
- **Ports**: Match the host side to the new port by editing the mapping to `- "8181:8181"` or parameterise it as `- "${LLAMA_PORT:-8080}:${LLAMA_ARG_PORT:-8080}"` for easy swaps between environments.

### Compose-wide tips
- Use targeted commands like `docker compose up chat-backend chat-frontend` to honour your overrides without launching unused services.
- Keep per-environment settings isolated by storing them in `env.development`, `env.staging`, etc., then launch with `docker compose --env-file env.staging up`.

## Data Storage Layout
- `./data` (host) ↔ `/data` (backend container): Holds `local.db` (SQLite) and any files the backend writes. Modify the volume target in `docker-compose.yml` if you need a different in-container path.
- `APP_DB_PATH`, `APP_DATA_PATH`, `APP_ASSETS_PATH`: These environment variables (defined in `docker-compose.yml`) tell the backend where to read/write. Set them to an alternate mount when using managed volumes or cloud storage.
- `./models` (host) ↔ `/llm-models` (llama container): Store `.gguf` weights here. Each model can live in its own subfolder; update the compose volume path to switch models quickly.
- `chat-frontend/.next` output ships inside the image. To persist uploads or caches, add an extra `volumes` entry under `chat-frontend` that maps a host directory into the desired in-container path.

## Runtime Modes

### Lite Mode (frontend + backend only)
1. Ensure the backend has whatever API keys it needs by exporting them before invoking Compose (e.g. `export OPENAI_API_KEY=...`).
2. Build and launch just the UI and API:  
   `docker compose up --build chat-backend chat-frontend`
3. Visit `http://localhost:3000`. The frontend proxies API requests to `http://localhost:8000` out of the box.

### Heavy Mode (frontend + backend + local LLaMA server)
1. Prepare GPU drivers and the NVIDIA Container Toolkit on the host.
2. Place your `.gguf` model under `./models` and update the volume path in `docker-compose.yml` if needed.
3. Launch all services, rebuilding the llama image if dependencies changed:  
   `docker compose up --build`
4. The LLaMA HTTP server listens on `http://localhost:8080`; configure the backend to call it via environment variables or service discovery, depending on your agent setup.

Shut everything down with `docker compose down`. Add `--volumes` if you want to wipe the SQLite database and any cached assets stored in `./data`.
