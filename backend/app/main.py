from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.middleware import RequestContextMiddleware
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.infra.cache.redis_client import get_redis_factory
from app.infra.db.session import get_session_manager
from app.infra.telemetry.langsmith import configure_langsmith 
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.modules.agent.router import router as ai_router
from app.modules.agent.search.service import sweep_stale_search_sessions
from app.modules.auth.router import router as auth_router
from app.modules.highlights.router import router as highlights_router
from app.modules.notebooks.router import router as notebooks_router
from app.modules.notes.router import router as notes_router
from app.modules.settings.router import router as settings_router
from app.modules.sources.router import router as sources_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    setup_tracing(app=app, engine=get_session_manager().engine, settings=settings)
    configure_langsmith(settings)
    app.state.settings = settings
    sweep_stop = asyncio.Event()
    sweep_task = asyncio.create_task(_search_sweep_worker(sweep_stop))

    try:
        yield
    finally:
        sweep_stop.set()
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        await get_session_manager().dispose()
        await get_redis_factory().close()
        shutdown_tracing()


async def _search_sweep_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await sweep_stale_search_sessions(limit=200)
        except Exception:
            # 扫尾任务不应影响主服务生命周期
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=120)
        except TimeoutError:
            continue


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(ai_router, prefix=settings.api_prefix)
    app.include_router(notebooks_router, prefix=settings.api_prefix)
    app.include_router(notes_router, prefix=settings.api_prefix)
    app.include_router(highlights_router, prefix=settings.api_prefix)
    app.include_router(settings_router, prefix=settings.api_prefix)
    app.include_router(sources_router, prefix=settings.api_prefix)

    return app


app = create_app()
