# app/main.py
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

from app.config import settings
from app.modules.agent_log.router import router as agent_log_router
from app.modules.agreements.router import router as agreements_router
from app.modules.findings.router import router as findings_router
from app.modules.inspections.router import router as inspections_router
from app.modules.inspectors.router import router as inspectors_router
from app.modules.media.router import router as media_router
from app.modules.observations.router import router as observations_router
from app.modules.properties.router import router as properties_router
from app.modules.reports.router import router as reports_router
from app.modules.tenants.router import internal_router, router as tenants_router
from app.shared.db.session import get_engine
from app.shared.middleware.tenant import TenantMiddleware

# Ensure all models are registered in SQLAlchemy metadata before any FK
# resolution (e.g. ForeignKey("tenants.id") on TenantScopedMixin) is needed.
import app.modules.tenants.models  # noqa: F401
import app.modules.inspectors.models  # noqa: F401
import app.modules.properties.models  # noqa: F401
import app.modules.inspections.models  # noqa: F401
import app.modules.agreements.models  # noqa: F401
import app.modules.findings.models  # noqa: F401
import app.modules.reports.models  # noqa: F401
import app.modules.media.models  # noqa: F401
import app.modules.observations.models  # noqa: F401
import app.modules.agent_log.models  # noqa: F401

app = FastAPI(title="MCAG Technologies API")
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants_router)
if settings.internal_routes_enabled:
    app.include_router(internal_router)
app.include_router(properties_router)
app.include_router(inspectors_router)
app.include_router(inspections_router)
app.include_router(agreements_router)
app.include_router(findings_router)
app.include_router(observations_router)
app.include_router(reports_router)
app.include_router(media_router)
app.include_router(agent_log_router)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "environment": settings.environment})


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok", "db": "ok", "environment": settings.environment})
    except Exception as e:
        logger.error("Readiness check DB error: %s: %s", type(e).__name__, e)
        return JSONResponse(
            {"status": "degraded", "db": "unavailable", "environment": settings.environment},
            status_code=503,
        )
