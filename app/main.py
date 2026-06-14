# =============================================================================
# app/main.py
# FastAPI application — async, production-structured, fully documented
#
# Startup order: lifespan() → DB init → router registration → CORS → serve
# =============================================================================

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db, init_db
from app.schemas.schemas import (
    HealthResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from app.services.services import WorkflowJobService

# ---------------------------------------------------------------------------
# Logging — structured format for production log aggregators (CloudWatch, Datadog)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated on_startup/on_shutdown hooks
# Runs DB table creation on boot; add cache warm-up or queue consumers here
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    await init_db()
    logger.info("Database ready.")
    yield
    logger.info("Shutting down — releasing DB pool.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Production-grade document ingestion, LlamaIndex parsing, "
        "and async workflow tracking API."
    ),
    docs_url="/docs",           # Swagger UI
    redoc_url="/redoc",         # ReDoc alternative
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTES
# =============================================================================

# ---------------------------------------------------------------------------
# Health check — load-balancer & ECS container health target
# ---------------------------------------------------------------------------
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Infrastructure"],
    summary="Health & DB connectivity probe",
)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    Returns 200 if the app is running and Postgres is reachable.
    Returns 503 if the DB connection fails — critical for orchestration layers.
    """
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error(f"DB health check failed: {exc}")
        db_status = "unreachable"

    if db_status != "connected":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unreachable",
        )

    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        db=db_status,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — submit a document for processing
# ---------------------------------------------------------------------------
@app.post(
    f"{settings.API_PREFIX}/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workflow Jobs"],
    summary="Submit a document for LlamaIndex parsing and DB tracking",
)
async def create_job(
    payload: JobCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    Pipeline executed on this call:
    1. Validate request via Pydantic
    2. Persist job as PENDING in PostgreSQL
    3. Run LlamaIndex document parse (SentenceSplitter + node extraction)
    4. Persist extracted entities as child rows
    5. Update job status → COMPLETED | FAILED
    6. Return full job record with entities
    """
    service = WorkflowJobService(db)
    try:
        job = await service.create_and_process_job(payload)
        return job
    except Exception as exc:
        logger.error(f"Job creation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow processing error: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/jobs — paginated list of all jobs
# ---------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/jobs",
    response_model=JobListResponse,
    tags=["Workflow Jobs"],
    summary="List all workflow jobs (paginated)",
)
async def list_jobs(
    skip:  int = Query(default=0,  ge=0,  description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    service = WorkflowJobService(db)
    jobs = await service.list_jobs(skip=skip, limit=limit)
    return JobListResponse(total=len(jobs), jobs=jobs)


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id} — fetch a single job with entities
# ---------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/jobs/{{job_id}}",
    response_model=JobResponse,
    tags=["Workflow Jobs"],
    summary="Fetch a single workflow job by UUID",
)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowJobService(db)
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    return job


# ---------------------------------------------------------------------------
# Global exception handler — catch unhandled errors, never leak stack traces
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error. Check application logs."},
    )
