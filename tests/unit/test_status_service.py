"""
Unit tests for StatusService.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from knowledgebase.core.config import Settings
from knowledgebase.core.models import (
    AggregateStats,
    DiagnosticReport,
    EndpointTestResult,
    FullStatusResponse,
    SyncStatusInfo,
    ToolTestResult,
)
from knowledgebase.services.status_service import StatusService


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings()


@pytest_asyncio.fixture
async def status_service(settings: Settings) -> StatusService:
    """Create and initialize StatusService."""
    service = StatusService(settings)
    await service.initialize()
    return service


@pytest.mark.asyncio
async def test_status_service_initialization(status_service: StatusService) -> None:
    """Test StatusService initializes correctly."""
    assert status_service is not None
    health = await status_service.health_check()
    assert health["healthy"] in [True, False]


@pytest.mark.asyncio
async def test_test_all_mcp_tools(status_service: StatusService) -> None:
    """Test MCP tool testing."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "ok"}]}}
        )
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        results = await status_service.test_all_mcp_tools()

        assert isinstance(results, dict)
        assert len(results) > 0
        for name, result in results.items():
            assert isinstance(result, ToolTestResult)
            assert result.name == name
            assert result.status in ["pass", "fail"]
            assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_test_all_api_endpoints(status_service: StatusService) -> None:
    """Test API endpoint testing."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "{}"
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        results = await status_service.test_all_api_endpoints()

        assert isinstance(results, dict)
        assert len(results) > 0
        for path, result in results.items():
            assert isinstance(result, EndpointTestResult)
            assert result.path == path
            assert result.method in ["GET", "POST"]
            assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_get_sync_status_no_file(status_service: StatusService, tmp_path) -> None:
    """Test getting sync status when status.json doesn't exist."""
    # StatusService checks both config_dir and data_dir; isolate both so a
    # local developer data/status.json cannot leak into the unit test.
    empty_config = tmp_path / "config"
    empty_data = tmp_path / "data"
    empty_config.mkdir()
    empty_data.mkdir()
    with (
        patch.object(status_service.config, "config_dir", empty_config),
        patch.object(status_service.config, "data_dir", empty_data),
    ):
        status = await status_service.get_sync_status()

        assert isinstance(status, SyncStatusInfo)
        assert status.last_sync_time is None
        assert status.sync_duration_seconds == 0.0


@pytest.mark.asyncio
async def test_get_sync_status_with_file(status_service: StatusService, tmp_path) -> None:
    """Test getting sync status with existing status.json."""
    # Create status.json
    status_data = {
        "last_sync": "2026-03-16T10:00:00",
        "sync_duration_seconds": 45.2,
        "indices_synced": 5,
        "documents_synced": 1234,
        "sync_errors": [],
    }
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    status_file = config_dir / "status.json"
    status_file.write_text(json.dumps(status_data))

    with (
        patch.object(status_service.config, "config_dir", config_dir),
        patch.object(status_service.config, "data_dir", data_dir),
    ):
        status = await status_service.get_sync_status()

        assert isinstance(status, SyncStatusInfo)
        assert status.sync_duration_seconds == 45.2
        assert status.indices_synced == 5
        assert status.documents_synced == 1234


@pytest.mark.asyncio
async def test_get_aggregate_stats(status_service: StatusService) -> None:
    """Test getting aggregate statistics."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "total_documents": 1234,
                "total_indices": 5,
                "uptime_seconds": 86400,
                "memory_usage_mb": 256,
                "storage_usage_gb": 1.2,
                "total_searches": 100,
            }
        )
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        stats = await status_service.get_aggregate_stats()

        assert isinstance(stats, AggregateStats)
        assert stats.total_documents == 1234
        assert stats.total_indices == 5
        assert stats.uptime_formatted == "1d 0h"
        assert stats.memory_usage_mb == 256


@pytest.mark.asyncio
async def test_generate_diagnostic_report(status_service: StatusService) -> None:
    """Test diagnostic report generation."""
    tools = {
        "kb_health": ToolTestResult(name="kb_health", status="pass", duration_ms=10),
        "kb_stats": ToolTestResult(name="kb_stats", status="pass", duration_ms=15),
    }
    endpoints = {
        "/health": EndpointTestResult(path="/health", method="GET", status_code=200, duration_ms=5),
        "/api/v1/system/stats": EndpointTestResult(
            path="/api/v1/system/stats", method="GET", status_code=200, duration_ms=20
        ),
    }

    report = await status_service.generate_diagnostic_report(tools, endpoints)

    assert isinstance(report, DiagnosticReport)
    assert report.tools_passed == 2
    assert report.tools_failed == 0
    assert report.endpoints_passed == 2
    assert report.endpoints_failed == 0
    assert len(report.issues) == 0


@pytest.mark.asyncio
async def test_get_full_status(status_service: StatusService) -> None:
    """Test getting full comprehensive status."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "total_documents": 100,
                "total_indices": 3,
                "uptime_seconds": 3600,
                "memory_usage_mb": 128,
                "storage_usage_gb": 0.5,
                "total_searches": 50,
            }
        )
        mock_response.text = "{}"
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        status = await status_service.get_full_status()

        assert isinstance(status, FullStatusResponse)
        assert status.overall_status in ["healthy", "degraded"]
        assert isinstance(status.tools, list)
        assert isinstance(status.endpoints, list)
        assert isinstance(status.sync, SyncStatusInfo)
        assert isinstance(status.stats, AggregateStats)
        assert isinstance(status.diagnostics, DiagnosticReport)


def test_format_uptime() -> None:
    """Test uptime formatting."""
    assert StatusService._format_uptime(30) == "30s"
    assert StatusService._format_uptime(300) == "5m"
    assert StatusService._format_uptime(3600) == "1h 0m"
    assert StatusService._format_uptime(86400) == "1d 0h"
    assert StatusService._format_uptime(90000) == "1d 1h"


def test_format_time_ago() -> None:
    """Test time-ago formatting."""
    from datetime import timezone

    now = datetime.now(timezone.utc)
    assert StatusService._format_time_ago(now) == "now"

    from datetime import timedelta

    # 30 minutes ago
    past = now - timedelta(minutes=30)
    result = StatusService._format_time_ago(past)
    assert "ago" in result
    assert "m" in result or "h" in result


@pytest.mark.asyncio
async def test_status_service_handles_errors(status_service: StatusService) -> None:
    """Test StatusService handles errors gracefully."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.side_effect = Exception("Connection error")

        # Should not raise, but handle gracefully
        stats = await status_service.get_aggregate_stats()
        assert isinstance(stats, AggregateStats)


@pytest.mark.asyncio
async def test_status_service_concurrent_calls(status_service: StatusService) -> None:
    """Test StatusService handles concurrent calls correctly."""
    import asyncio

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(
            return_value={
                "total_documents": 100,
                "total_indices": 3,
                "uptime_seconds": 3600,
                "memory_usage_mb": 128,
                "storage_usage_gb": 0.5,
                "total_searches": 50,
            }
        )
        mock_response.text = "{}"
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        # Run multiple concurrent status checks
        results = await asyncio.gather(
            status_service.get_full_status(),
            status_service.get_full_status(),
            status_service.get_aggregate_stats(),
        )

        assert len(results) == 3
        assert all(r is not None for r in results)
