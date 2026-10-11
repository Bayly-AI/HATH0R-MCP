# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# Stage 1: Build & Dependencies
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt pyproject.toml* ./
RUN if [ -f requirements.txt ]; then \
        pip install --prefix=/install -r requirements.txt; \
    elif [ -f pyproject.toml ]; then \
        pip install --prefix=/install .; \
    fi

# ------------------------------------------------------------------------------
# Stage 2: Hardened Non-Root Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.11/site-packages:$PYTHONPATH"

# Create dedicated non-root user (UID/GID 10001)
RUN groupadd -g 10001 hath0r && \
    useradd -u 10001 -g hath0r -s /bin/sh -m hath0r

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /install

# Copy application source code with non-root ownership
COPY --chown=hath0r:hath0r . /app

# Switch to non-root user
USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

ENTRYPOINT ["python3", "-m", "hath0r_mcp"]
