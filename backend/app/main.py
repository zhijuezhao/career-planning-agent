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
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
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

    # Scheduler lifespan
    from app.core.job_agent.scheduler.adaptive_scheduler import AdaptiveScheduler
    from app.core.job_agent.scheduler.source_registry import SourceRegistry

    scheduler = AdaptiveScheduler(registry=SourceRegistry())

    @app.on_event("startup")
    async def start_scheduler():
        scheduler.start()
        logger.info("Scheduler started on application startup")

    @app.on_event("shutdown")
    async def stop_scheduler():
        scheduler.shutdown()
        logger.info("Scheduler shutdown on application shutdown")

    @app.on_event("startup")
    async def warm_llm_registry():
        """预热模型配置快照（B2-1）。

        DB 里没有配置时快照为空 → 网关继续用 env（行为不变）；
        预热失败只告警不阻塞启动，避免数据库暂时不可用导致整个服务起不来。
        """
        from app.core.llm.registry import reload_registry
        from app.infrastructure.database import async_session_factory

        try:
            async with async_session_factory() as session:
                await reload_registry(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("模型配置快照预热失败，沿用 env 配置 | error={}", exc)

    # Expose scheduler on app.state for access from routes
    app.state.scheduler = scheduler

    logger.info("Application created | env={} | debug={}", settings.app_env, settings.is_development)

    return app


app = create_app()
