from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    from app.infrastructure.logging import setup_logging
    setup_logging()

    from app.infrastructure.langsmith import setup_langsmith
    setup_langsmith()

    app = FastAPI(
        title="Career Planning Agent API",
        description="AI-driven career planning platform for college students",
        version="0.1.0",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info("{} {} | client={}", request.method, request.url.path, request.client.host)
        response = await call_next(request)
        logger.info("{} {} | status={}", request.method, request.url.path, response.status_code)
        return response

    from app.api.v1 import router as api_v1_router
    app.include_router(api_v1_router, prefix="/api/v1")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "app": settings.app_name, "env": settings.app_env}

    logger.info("Application created | env={} | debug={}", settings.app_env, settings.is_development)

    return app


app = create_app()
