"""QUE-Agent FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, health, ops
from app.core.config import get_settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    from app.knowledge import validate_knowledge_manifest

    kb_problems = validate_knowledge_manifest()
    logger.info(
        "que_agent_starting",
        env=settings.app_env,
        version=settings.app_version,
        llm_model=settings.llm_model,
        insecure_local_auth=settings.allow_insecure_local_no_auth,
        knowledge_ok=not kb_problems,
        knowledge_problems=kb_problems or None,
    )
    if kb_problems:
        logger.error("knowledge_manifest_invalid", problems=kb_problems)
    yield
    logger.info("que_agent_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.is_local

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Que-Service-Key"],
            expose_headers=["X-Accel-Buffering"],
        )

    application.include_router(health.router)
    application.include_router(chat.router)
    application.include_router(ops.router)
    return application


app = create_app()
