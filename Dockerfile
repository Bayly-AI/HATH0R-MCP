# Dockerfile for BAI-1-NATION-MCP Service
FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG APP_VERSION=1.0.1
ARG AWS_PUSH_COUNTER=0
ARG AWS_RELEASE_VER=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
    APP_VERSION=${APP_VERSION} \
    AWS_PUSH_COUNTER=${AWS_PUSH_COUNTER} \
    AWS_RELEASE_VER=${AWS_RELEASE_VER}

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash mcp

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application and configs
COPY pyproject.toml README.md ./
COPY src ./src
COPY cfg ./cfg

# Install package
RUN pip install --no-deps .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/knowledgebase /app/data/indices && \
    chown -R mcp:mcp /app

# Switch to non-root user
USER mcp

# Expose container port
EXPOSE 8083

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8083/ready', timeout=5)"

# Start FastMCP server
CMD ["python", "-m", "uvicorn", "knowledgebase.server:app", "--host", "0.0.0.0", "--port", "8083"]
