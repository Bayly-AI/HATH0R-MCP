"""FastAPI app factory for serving the KnowledgeBase UI dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

DEFAULT_API_BASE_URL = os.getenv("BaylyAI_KNOWLEDGEBASE_HOST", "http://localhost:8083")
_DEFAULT_STATIC_DIR = Path("lib/client/design-1.0/BaylyAI Knowledgebase Dashboard/dist")


def _resolve_static_dir(static_dir: str | Path | None) -> Path:
    """Resolve and normalize the target static assets directory."""
    if static_dir is None:
        candidate = _DEFAULT_STATIC_DIR
    elif isinstance(static_dir, Path):
        candidate = static_dir
    else:
        candidate = Path(static_dir)
    return candidate.expanduser().resolve()


def create_app(*, api_base_url: str | None = None, static_dir: str | Path | None = None) -> FastAPI:
    """Create the UI applet service.

    The service exposes:
    - `/__config__` for runtime API base URL injection
    - static dashboard assets at `/` when available
    """
    env_api_base_url = os.getenv("BaylyAI_KNOWLEDGEBASE_HOST")
    resolved_api_base_url = (
        api_base_url if api_base_url is not None else (env_api_base_url or DEFAULT_API_BASE_URL)
    )
    resolved_static_dir = _resolve_static_dir(static_dir)

    app = FastAPI(
        title="KnowledgeBase UI Applet",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/__config__")
    async def get_runtime_config() -> dict[str, str]:
        """Return runtime UI configuration for front-end bootstrapping."""
        return {"apiBaseUrl": resolved_api_base_url}

    if resolved_static_dir.exists():
        app.mount("/", StaticFiles(directory=resolved_static_dir, html=True), name="ui-static")
    else:

        @app.get("/")
        async def missing_assets() -> dict[str, Any]:
            """Return a clear message when UI assets are not yet built."""
            return {
                "message": "UI static assets not found. Build the UI dashboard first.",
                "staticDir": str(resolved_static_dir),
            }

    return app
