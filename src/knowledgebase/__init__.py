"""
KnowledgeBase Engine - AWS-integrated vector search platform.

This package provides semantic search capabilities with support for:
- Multiple embedding providers (OpenAI, Ollama)
- Multiple storage backends (OpenSearch Serverless, local)
- Hybrid search (kNN + BM25)
- Multi-index management
"""

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _get_version
from pathlib import Path
from knowledgebase.core.config import Settings, get_settings
from knowledgebase.core.models import Document, SearchResult


def _fallback_version_from_pyproject() -> str | None:
    """Best-effort fallback version lookup from a nearby pyproject.toml."""
    pattern = re.compile(r'^version\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)
    for parent in Path(__file__).resolve().parents:
        pyproject_path = parent / "pyproject.toml"
        if not pyproject_path.exists():
            continue
        try:
            contents = pyproject_path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = pattern.search(contents)
        if match:
            version = match.group(1).strip()
            if version:
                return version
    return None


try:
    # Use installed package metadata so the version is always in sync with
    # pyproject.toml and automated release tooling.
    __version__ = _get_version("hath0r-mcp")
except PackageNotFoundError:  # pragma: no cover - fallback during editable installs
    try:
        __version__ = _get_version("python-service-template")
    except PackageNotFoundError:
        __version__ = _fallback_version_from_pyproject() or "0.0.0"

__author__ = "Hath0r Team"

__all__ = [
    "__version__",
    "Settings",
    "get_settings",
    "Document",
    "SearchResult",
]
