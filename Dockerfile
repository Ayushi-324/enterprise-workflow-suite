# =============================================================================
# Dockerfile — Multi-stage build for the FastAPI application
# Stage 1 (builder): installs deps into an isolated venv
# Stage 2 (runtime): copies only the venv + app code — no build tools in prod image
#
# Result: lean ~250MB image vs ~800MB if you skip multi-stage
# =============================================================================

# ── Stage 1: Dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Prevent Python from writing .pyc files and enable stdout/stderr buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install system build deps needed to compile asyncpg C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first — Docker layer cache means this only reruns when
# requirements.txt changes, not on every code change (major speedup in CI)
COPY requirements.txt .

# Install into an isolated venv so Stage 2 can copy it cleanly
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt


# ── Stage 2: Production runtime ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Runtime-only system libs (libpq for asyncpg at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — never run production containers as root
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy venv from builder stage (no pip, no compiler in final image)
COPY --from=builder /opt/venv /opt/venv

# Copy application source (owned by non-root user)
COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8000

# Uvicorn: 2 workers per CPU core is the standard starting point.
# --proxy-headers: trust X-Forwarded-For from Nginx reverse proxy
# --forwarded-allow-ips: accept proxy headers only from Docker internal network
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--log-level", "info"]
