"""Unit tests for the runtime_start helper module.

These tests focus on configuration resolution logic and do not actually
invoke Docker or Uvicorn.
"""

from __future__ import annotations
import importlib

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from knowledgebase.cli import runtime_start


@pytest.mark.unit
class TestResolveMode:
    """Tests for resolving the effective runtime start mode."""

    def test_cli_package_lazily_imports_main_module(self) -> None:
        """Importing the package should not eagerly load the Rich-based CLI."""

        sys.modules.pop("knowledgebase.cli.main", None)
        sys.modules.pop("knowledgebase.cli", None)

        cli_package = importlib.import_module("knowledgebase.cli")

        assert "knowledgebase.cli.main" not in sys.modules

        _ = cli_package.cli

        assert "knowledgebase.cli.main" in sys.modules

    def test_explicit_mode_wins_over_env_and_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit mode argument should override environment and defaults."""

        config: dict[str, Any] = {
            "default_start_mode": "docker",
            "modes": {"docker": {}, "local": {}},
        }

        monkeypatch.setenv("KB_START_MODE", "local")

        mode = runtime_start._resolve_mode(config, explicit_mode="docker")

        assert mode == "docker"

    def test_env_mode_used_when_no_explicit_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KB_START_MODE should be used when no explicit mode is provided."""

        config: dict[str, Any] = {
            "default_start_mode": "docker",
            "modes": {"docker": {}, "local": {}},
        }

        monkeypatch.setenv("KB_START_MODE", "local")

        mode = runtime_start._resolve_mode(config, explicit_mode=None)

        assert mode == "local"

    def test_default_mode_used_when_no_env_or_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default_start_mode from the config should be used as a fallback."""

        config: dict[str, Any] = {
            "default_start_mode": "local",
            "modes": {"docker": {}, "local": {}},
        }

        monkeypatch.delenv("KB_START_MODE", raising=False)

        mode = runtime_start._resolve_mode(config, explicit_mode=None)

        assert mode == "local"


@pytest.mark.unit
class TestMainFallback:
    """Tests for the main() entry point's fallback behavior."""

    def test_unknown_mode_falls_back_to_docker_and_calls_start_docker(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unknown runtime mode should fall back to docker and call _start_docker."""

        called: dict[str, Any] = {"docker": False}

        def _fake_start_docker(mode_config: dict[str, Any]) -> None:  # type: ignore[unused-ignore]
            called["docker"] = True

        def _fake_start_local(
            mode_config: dict[str, Any],
        ) -> None:  # pragma: no cover - should not be called
            raise AssertionError("_start_local should not be invoked in this test")

        monkeypatch.setattr(runtime_start, "_start_docker", _fake_start_docker)
        monkeypatch.setattr(runtime_start, "_start_local", _fake_start_local)

        # Ensure there is no cfg/cfg.json so that the default runtime config is used.
        # We call main() with an explicit unknown mode to trigger the fallback branch.
        runtime_start.main(explicit_mode="unknown-mode")

        assert called["docker"] is True

    def test_main_with_local_mode_calls_start_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main(explicit_mode="local") should delegate to _start_local."""

        called: dict[str, bool] = {"local": False}

        def _fake_start_local(mode_config: dict[str, Any]) -> None:  # type: ignore[unused-ignore]
            called["local"] = True

        monkeypatch.setattr(runtime_start, "_start_local", _fake_start_local)

        runtime_start.main(explicit_mode="local")

        assert called["local"] is True


@pytest.mark.unit
class TestStartHelpers:
    """Tests for the low-level _start_docker and _start_local helpers."""

    def test_start_docker_success_path_runs_compose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_start_docker should invoke docker compose and not exit on success."""

        recorded: dict[str, Any] = {}

        class DummyResult:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode

        def fake_run(cmd: list[str], check: bool = False) -> DummyResult:  # noqa: FBT001, FBT002
            recorded["cmd"] = cmd
            recorded["check"] = check
            return DummyResult(returncode=0)

        monkeypatch.setattr(runtime_start.subprocess, "run", fake_run)

        mode_config = {"compose_file": "docker-compose.yml", "service": "kb", "port": 9001}
        runtime_start._start_docker(mode_config)

        assert recorded["cmd"][:4] == ["docker", "compose", "-f", "docker-compose.yml"]
        assert "kb" in recorded["cmd"]

    def test_start_docker_failure_exits_with_return_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-zero docker compose exit codes should cause SystemExit."""

        class DummyResult:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode

        def fake_run(cmd: list[str], check: bool = False) -> DummyResult:  # noqa: FBT001, FBT002
            del cmd, check
            return DummyResult(returncode=5)

        monkeypatch.setattr(runtime_start.subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as excinfo:
            runtime_start._start_docker({"compose_file": "docker-compose.yml"})

        assert excinfo.value.code == 5

    def test_start_local_uses_uvicorn_run_with_expected_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_start_local should call uvicorn.run with the resolved host/port/reload."""

        calls: list[dict[str, Any]] = []

        def fake_run(app: str, host: str, port: int, reload: bool) -> None:  # noqa: FBT001
            calls.append({"app": app, "host": host, "port": port, "reload": reload})

        fake_uvicorn = SimpleNamespace(run=fake_run)
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

        mode_config = {"host": "127.0.0.1", "port": 9000, "reload": True}
        runtime_start._start_local(mode_config)

        assert calls
        call = calls[0]
        assert call["app"] == "knowledgebase.api.main:app"
        assert call["host"] == "127.0.0.1"
        assert call["port"] == 9000
        assert call["reload"] is True
