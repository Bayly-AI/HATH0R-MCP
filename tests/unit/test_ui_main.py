"""Unit tests for the KnowledgeBase UI CLI entry point.

These tests exercise the click-based `kb-ui` launcher defined in
`knowledgebase.ui.main`, without starting a real HTTP server or opening a
browser.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner

from knowledgebase.ui.main import main as ui_main


@pytest.mark.unit
class TestUiMainCli:
    """Tests for the UI applet CLI wrapper in `knowledgebase.ui.main`."""

    def test_main_uses_env_var_and_starts_uvicorn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`main` should read BaylyAI_KNOWLEDGEBASE_HOST and call uvicorn.run()."""

        calls: dict[str, Any] = {}

        # Arrange environment and dependencies.
        monkeypatch.setenv("BaylyAI_KNOWLEDGEBASE_HOST", "http://example.invalid:9999")

        def fake_create_app(*, api_base_url: str) -> object:  # type: ignore[override]
            calls["api_base_url"] = api_base_url
            return object()

        def fake_uvicorn_run(
            app: object, host: str, port: int, log_level: str
        ) -> None:  # noqa: D401
            """Record the uvicorn.run parameters instead of starting a server."""

            calls["uvicorn_args"] = {
                "app": app,
                "host": host,
                "port": port,
                "log_level": log_level,
            }

        from knowledgebase.ui import main as ui_main_module

        monkeypatch.setattr(ui_main_module, "create_app", fake_create_app)
        monkeypatch.setattr(ui_main_module.uvicorn, "run", fake_uvicorn_run)

        runner = CliRunner()

        # Act: disable browser opening so we only cover the core startup path.
        result = runner.invoke(
            ui_main, ["--host", "0.0.0.0", "--port", "9000", "--no-open-browser"]
        )

        # Assert
        assert result.exit_code == 0, result.output
        assert calls["api_base_url"] == "http://example.invalid:9999"
        assert calls["uvicorn_args"]["host"] == "0.0.0.0"
        assert calls["uvicorn_args"]["port"] == 9000
        assert calls["uvicorn_args"]["log_level"] == "info"

    def test_main_opens_browser_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`main` should attempt to open a browser when `open_browser` is True."""

        opened: dict[str, Any] = {}

        def fake_create_app(*, api_base_url: str) -> object:  # type: ignore[override]
            opened["api_base_url"] = api_base_url
            return object()

        def fake_uvicorn_run(
            app: object, host: str, port: int, log_level: str
        ) -> None:  # noqa: D401
            """Stub uvicorn.run so the test exits immediately."""

            opened["uvicorn_host"] = host
            opened["uvicorn_port"] = port
            opened["uvicorn_log_level"] = log_level

        def fake_open(url: str, new: int = 0) -> bool:  # noqa: D401
            """Record the URL passed to webbrowser.open()."""

            opened["url"] = url
            opened["new"] = new
            return True

        from knowledgebase.ui import main as ui_main_module

        monkeypatch.delenv("BaylyAI_KNOWLEDGEBASE_HOST", raising=False)
        monkeypatch.setattr(ui_main_module, "create_app", fake_create_app)
        monkeypatch.setattr(ui_main_module.uvicorn, "run", fake_uvicorn_run)
        monkeypatch.setattr(ui_main_module.webbrowser, "open", fake_open)

        runner = CliRunner()
        result = runner.invoke(ui_main, ["--host", "127.0.0.1", "--port", "8081"])

        assert result.exit_code == 0, result.output
        # Browser should have been opened with the computed URL.
        assert opened["url"] == "http://127.0.0.1:8081/"
        assert opened["uvicorn_host"] == "127.0.0.1"
        assert opened["uvicorn_port"] == 8081

    def test_main_exits_with_error_when_create_app_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`main` should exit with status 1 when the UI app cannot be created."""

        def failing_create_app(*, api_base_url: str) -> object:  # type: ignore[override]
            raise RuntimeError("boom")

        from knowledgebase.ui import main as ui_main_module

        monkeypatch.setattr(ui_main_module, "create_app", failing_create_app)

        runner = CliRunner()
        result = runner.invoke(ui_main, ["--no-open-browser"])

        assert result.exit_code == 1
        assert "Failed to start UI applet" in result.output
