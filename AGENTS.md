# AGENTS.md

## Cursor Cloud specific instructions

### Architecture overview

This is an AI research assistant application with two main components:

| Component | Tech | Port |
|-----------|------|------|
| Backend (FastAPI) | Python 3.12, SQLAlchemy, LangChain | 8080 |
| Frontend (React SPA) | React 19, Vite 7 | 5173 |
| Worker | Same Python venv, Kafka consumer | — |
| Scheduler | Same Python venv, periodic tasks | — |

Infrastructure services run via Docker Compose (see `docker-compose.yml` for service names).

### Starting infrastructure

Start the four core infra services using Docker Compose (use the service names from `docker-compose.yml`), then wait for healthy status before running migrations:

```bash
cd backend && .venv/bin/python -m alembic upgrade head
```

### Starting dev services

`scripts/dev.sh` manages all four processes (backend, worker, scheduler, frontend):

```bash
SKIP_NATIVE_LIB_SETUP=1 bash scripts/dev.sh start   # start all
bash scripts/dev.sh status                             # check
bash scripts/dev.sh stop                               # stop all
```

### Lint and tests

- **Backend lint**: `cd backend && .venv/bin/ruff check .`
- **Frontend lint**: `cd frontend && npx eslint .`
- **Backend tests**: `cd backend && .venv/bin/pytest` (requires running infrastructure)
- **Frontend build check**: `cd frontend && npx vite build`

### Non-obvious caveats

- The `.env` file lives at the repo root (not inside `backend/` or `frontend/`). Copy from `.env.example` on first setup. Vite loads env vars from the repo root via `envDir` config.
- The backend venv is created at `backend/.venv` (not the repo root) by `uv sync`.
- `libmagic1` (system package) is needed by `python-magic`. Set `SKIP_NATIVE_LIB_SETUP=1` to skip the auto-install check in `dev.sh`.
- Docker must be running before `dev.sh start`, as the backend connects to DB, cache, and message queue on startup.
- The frontend proxies `/api` requests to the backend via Vite's dev proxy (`VITE_DEV_PROXY_TARGET` in `.env`).
- Alembic migrations use settings from `app.core.config` which reads the repo-root `.env`.
- The `remark-processor` tool (`tools/remark-processor/`) needs its own `npm install`.
