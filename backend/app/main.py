from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.middleware import RequestContextMiddleware
from app.core.config import get_settings
from app.infra.cache.redis_client import get_redis_factory
from app.infra.db.session import get_session_manager
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.langsmith import get_langsmith_client
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.modules.auth.router import router as auth_router
from app.modules.notebooks.router import router as notebooks_router
from app.modules.notes.router import router as notes_router
from app.modules.settings.router import router as settings_router
from app.modules.search.router import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    setup_tracing(app=app, engine=get_session_manager().engine, settings=settings)
    app.state.settings = settings
    app.state.langsmith = get_langsmith_client()

    try:
        yield
    finally:
        langsmith_client = getattr(app.state, "langsmith", None)
        if langsmith_client is not None:
            close = getattr(langsmith_client, "close", None)
            if callable(close):
                close()

        await get_session_manager().dispose()
        await get_redis_factory().close()
        shutdown_tracing()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

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
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(notebooks_router, prefix=settings.api_prefix)
    app.include_router(notes_router, prefix=settings.api_prefix)
    app.include_router(settings_router, prefix=settings.api_prefix)
    app.include_router(search_router, prefix=settings.api_prefix)

    return app


app = create_app()
