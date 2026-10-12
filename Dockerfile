# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# Stage 1: Build & Dependencies
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ARG GIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG APP_VERSION=1.2.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt pyproject.toml* README.md* ./
COPY src ./src

RUN if [ -f requirements.txt ]; then \
        pip install --prefix=/install -r requirements.txt; \
    fi && \
    if [ -f pyproject.toml ]; then \
        pip install --prefix=/install --no-deps .; \
    fi

# ------------------------------------------------------------------------------
# Stage 2: Hardened Non-Root Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

ARG GIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG APP_VERSION=1.2.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
    APP_VERSION=${APP_VERSION} \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/app/src:/install/lib/python3.11/site-packages:$PYTHONPATH" \
    HATH0R_MCP_KNOWLEDGE_ROOT=/app/knowledgebase/canonical

# Create dedicated non-root user (UID/GID 10001)
RUN groupadd -g 10001 hath0r && \
    useradd -u 10001 -g hath0r -s /bin/sh -m hath0r

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /install

# Copy application source code and configs with non-root ownership
COPY --chown=hath0r:hath0r . /app

# Create necessary directories for local runtime persistence
RUN mkdir -p /app/data /app/logs /app/data/indices && \
    chown -R hath0r:hath0r /app

# Switch to non-root user
USER 10001:10001

EXPOSE 8083

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8083/ready', timeout=5)" || exit 1

CMD ["python3", "-m", "uvicorn", "knowledgebase.server:app", "--host", "0.0.0.0", "--port", "8083"]
