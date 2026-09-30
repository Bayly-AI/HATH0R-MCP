"""Runtime startup helper for KnowledgeBase Engine.

This module reads the runtime configuration (cfg/cfg.json) and starts the
KnowledgeBase API using either Docker Compose (default) or a local Uvicorn
server. It is intended to be invoked from the Makefile or programmatically.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - subprocess usage is controlled and legitimate
import sys
from pathlib import Path
from typing import Any, Final

try:
    from rich.console import Console
except ModuleNotFoundError:  # pragma: no cover - exercised in runtime containers

    class Console:  # type: ignore[no-redef]
        """Minimal fallback console when Rich is unavailable."""

        def print(self, *args: object, **kwargs: object) -> None:
            del kwargs
            print(*args)


console: Final[Console] = Console()


DEFAULT_RUNTIME_CONFIG: Final[dict[str, Any]] = {
    "default_start_mode": "docker",
    "modes": {
        "docker": {
            "compose_file": "docker-compose.yml",
            "service": "knowledgebase-api",
            "port": 8000,
        },
        "local": {
            "host": "0.0.0.0",  # nosec B104 - intentional binding to all interfaces for API server
            "port": 8000,
            "reload": False,
        },
    },
}


def _load_runtime_config() -> dict[str, Any]:
    """Load runtime configuration from cfg/cfg.json if it exists.

    The configuration controls how the KnowledgeBase service is started, with
    support for multiple modes (e.g., ``docker`` and ``local``). If the file
    is missing or invalid, a built-in default configuration is used.

    Returns
    -------
    dict[str, Any]
        The runtime configuration dictionary containing at least
        ``default_start_mode`` and ``modes`` keys.
    """

    cfg_path = Path("cfg") / "cfg.json"
    if not cfg_path.exists():
        return DEFAULT_RUNTIME_CONFIG

    try:
        content = cfg_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        console.print(
            f"[yellow]Warning: failed to read runtime config at {cfg_path}: {exc}. "
            "Falling back to defaults.[/yellow]",
        )
        return DEFAULT_RUNTIME_CONFIG

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        return DEFAULT_RUNTIME_CONFIG

    # Merge with defaults to ensure required keys are present
    merged: dict[str, Any] = {
        "default_start_mode": runtime.get(
            "default_start_mode", DEFAULT_RUNTIME_CONFIG["default_start_mode"]
        ),
        "modes": {**DEFAULT_RUNTIME_CONFIG["modes"], **runtime.get("modes", {})},
    }
    return merged


def _resolve_mode(config: dict[str, Any], explicit_mode: str | None = None) -> str:
    """Resolve the effective start mode.

    Resolution order:

    1. ``explicit_mode`` argument (if provided)
    2. ``KB_START_MODE`` environment variable
    3. ``default_start_mode`` from configuration (fallbacks to ``docker``)

    Parameters
    ----------
    config:
        Runtime configuration dictionary.
    explicit_mode:
        Optional mode provided programmatically (e.g., ``"docker"`` or
        ``"local"``).

    Returns
    -------
    str
        The resolved mode name.
    """

    if explicit_mode:
        return explicit_mode

    env_mode = os.getenv("KB_START_MODE")
    if env_mode:
        return env_mode

    return str(config.get("default_start_mode", "docker"))


def _start_docker(mode_config: dict[str, Any]) -> None:
    """Start the KnowledgeBase API using Docker Compose.

    Parameters
    ----------
    mode_config:
        Configuration for the ``docker`` mode, including ``compose_file`` and
        optional ``service`` and ``port`` keys.
    """

    compose_file = str(mode_config.get("compose_file", "docker-compose.yml"))
    service = mode_config.get("service")
    port = int(mode_config.get("port", 8000))

    cmd = ["docker", "compose", "-f", compose_file, "up", "-d"]
    if isinstance(service, str) and service:
        cmd.append(service)

    console.print("[blue]Starting KnowledgeBase via Docker Compose...[/blue]")
    result = subprocess.run(cmd, check=False)  # nosec B603 - command array is controlled

    if result.returncode != 0:
        console.print(
            f"[red]Docker Compose failed with exit code {result.returncode}. "
            "Check your Docker installation and docker-compose configuration.[/red]",
        )
        sys.exit(result.returncode)

    console.print(
        f"[green]KnowledgeBase is starting in Docker.[/green] "
        f"Access it at [bold]http://localhost:{port}[/bold] once healthy.",
    )


def _start_local(mode_config: dict[str, Any]) -> None:
    """Start the KnowledgeBase API using a local Uvicorn server.

    Parameters
    ----------
    mode_config:
        Configuration for the ``local`` mode, including ``host``, ``port``, and
        optional ``reload`` keys.
    """

    import uvicorn  # Imported lazily to avoid dependency when only using Docker

    host = str(mode_config.get("host", "0.0.0.0"))  # nosec B104 - configurable bind address
    port = int(mode_config.get("port", 8000))
    reload = bool(mode_config.get("reload", False))

    console.print(
        f"[blue]Starting KnowledgeBase locally on http://{host}:{port} (reload={reload})...[/blue]",
    )

    uvicorn.run("knowledgebase.api.main:app", host=host, port=port, reload=reload)


def main(explicit_mode: str | None = None) -> None:
    """Entry point for starting the KnowledgeBase API.

    This function chooses the appropriate start mode based on configuration
    and starts the service accordingly. It is safe to call from the Makefile
    using ``poetry run python -m knowledgebase.cli.runtime_start``.

    Parameters
    ----------
    explicit_mode:
        Optional explicit mode override (e.g., ``"docker"`` or ``"local"``).
    """

    runtime_config = _load_runtime_config()
    modes = runtime_config.get("modes", {})

    mode = _resolve_mode(runtime_config, explicit_mode=explicit_mode)
    mode_config = modes.get(mode)

    if not isinstance(mode_config, dict):
        console.print(
            f"[yellow]Unknown runtime mode '{mode}'. Falling back to 'docker'.[/yellow]",
        )
        mode = "docker"
        mode_config = modes.get(mode, DEFAULT_RUNTIME_CONFIG["modes"]["docker"])

    if mode == "docker":
        _start_docker(mode_config)
    elif mode == "local":
        _start_local(mode_config)
    else:  # pragma: no cover - defensive fallback
        console.print(f"[red]Unsupported runtime mode: {mode}[/red]")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
