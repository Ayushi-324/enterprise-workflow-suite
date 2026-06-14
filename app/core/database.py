# =============================================================================
# app/core/database.py
# Async SQLAlchemy engine & session factory — production-grade setup
# Uses connection pooling, health checks, and per-request session lifecycle
# =============================================================================

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine — asyncpg driver, tuned pool for containerised Postgres
# NullPool is used in tests; swap to AsyncAdaptedQueuePool for production
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,           # SQL logging — flip off in prod
    pool_pre_ping=True,              # validate connections before checkout
    pool_size=10,                    # base pool connections kept alive
    max_overflow=20,                 # overflow connections allowed under load
    pool_timeout=30,                 # seconds to wait before raising timeout
    pool_recycle=1800,               # recycle connections every 30 min
)

# ---------------------------------------------------------------------------
# Session factory — expire_on_commit=False avoids lazy-load errors after
# the session closes (critical in async context where you return Pydantic models)
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Base model — all ORM models inherit from this
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dependency — FastAPI injects this into route handlers via Depends()
# Yields a session, guarantees commit/rollback/close on every request path
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Startup helper — called from lifespan to verify DB reachability
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Create all tables if they don't exist. Use Alembic for migrations in prod."""
    from app.models import models  # local import prevents circular deps   # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created successfully.")
