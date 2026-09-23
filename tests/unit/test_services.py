"""
Tests for service modules: BaseService, ServiceRegistry, MCPService, and SystemMonitoringService.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from knowledgebase.core.config import Settings
from knowledgebase.core.models import MCPServerStatus
from knowledgebase.services.base import BaseService, ServiceRegistry
from knowledgebase.services.mcp_service import MCPService
from knowledgebase.services.system_service import SystemMonitoringService


class ConcreteService(BaseService):
    """Concrete implementation of BaseService for testing."""

    async def _initialize_impl(self) -> None:
        """Test implementation of initialization."""
        await asyncio.sleep(0.01)

    async def _cleanup_impl(self) -> None:
        """Test implementation of cleanup."""
        await asyncio.sleep(0.01)

    async def _custom_health_check(self):
        """Test custom health check."""
        return {"custom_check": "passed"}


class TestBaseService:
    """Tests for BaseService class."""

    @pytest_asyncio.fixture
    async def service(self):
        """Create a concrete service instance."""
        config = Settings()
        service = ConcreteService(config)
        yield service
        # Cleanup after test
        if service.is_initialized:
            await service.cleanup()

    @pytest.mark.asyncio
    async def test_service_initialization(self, service):
        """Test service initialization."""
        assert not service.is_initialized
        assert not service.is_healthy

        await service.initialize()

        assert service.is_initialized
        assert service.is_healthy

    @pytest.mark.asyncio
    async def test_service_initialization_failure(self):
        """Test service initialization with error."""

        class FailingService(BaseService):
            async def _initialize_impl(self):
                raise ValueError("Initialization failed")

        config = Settings()
        service = FailingService(config)

        with pytest.raises(ValueError, match="Initialization failed"):
            await service.initialize()

        assert not service.is_initialized
        assert not service.is_healthy
        assert service._initialization_error is not None

    @pytest.mark.asyncio
    async def test_service_cleanup(self, service):
        """Test service cleanup."""
        await service.initialize()
        assert service.is_healthy

        await service.cleanup()
        assert not service.is_healthy

    @pytest.mark.asyncio
    async def test_service_cleanup_failure(self):
        """Test service cleanup with error."""

        class FailingCleanupService(BaseService):
            async def _initialize_impl(self):
                pass

            async def _cleanup_impl(self):
                raise RuntimeError("Cleanup failed")

        config = Settings()
        service = FailingCleanupService(config)
        await service.initialize()

        with pytest.raises(RuntimeError, match="Cleanup failed"):
            await service.cleanup()

    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """Test health check functionality."""
        await service.initialize()

        health = await service.health_check()

        assert health["healthy"] is True
        assert health["initialized"] is True
        assert health["service"] == "ConcreteService"
        assert health["custom_check"] == "passed"

    @pytest.mark.asyncio
    async def test_health_check_with_error(self, service):
        """Test health check when there's an initialization error."""
        service._initialization_error = ValueError("Test error")
        service._healthy = False

        health = await service.health_check()

        assert health["healthy"] is False
        assert "initialization_error" in health

    @pytest.mark.asyncio
    async def test_health_check_exception_handling(self, service):
        """Test health check handles exceptions gracefully."""

        async def failing_check():
            raise RuntimeError("Health check failed")

        service._custom_health_check = failing_check

        health = await service.health_check()

        assert health["healthy"] is False
        assert health["service"] == "ConcreteService"
        assert "error" in health

    @pytest.mark.asyncio
    async def test_ensure_initialized(self, service):
        """Test _ensure_initialized raises when not initialized."""
        with pytest.raises(RuntimeError, match="is not initialized"):
            service._ensure_initialized()

    @pytest.mark.asyncio
    async def test_ensure_initialized_success(self, service):
        """Test _ensure_initialized succeeds when initialized."""
        await service.initialize()
        service._ensure_initialized()  # Should not raise

    @pytest.mark.asyncio
    async def test_safe_execute_async(self, service):
        """Test _safe_execute with async function."""

        async def async_operation():
            return "result"

        result = await service._safe_execute("test_op", async_operation)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_safe_execute_sync(self, service):
        """Test _safe_execute with sync function."""

        def sync_operation():
            return "result"

        result = await service._safe_execute("test_op", sync_operation)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_safe_execute_error_handling(self, service):
        """Test _safe_execute error handling."""

        async def failing_operation():
            raise ValueError("Operation failed")

        with pytest.raises(ValueError, match="Operation failed"):
            await service._safe_execute("failing_op", failing_operation)


class TestServiceRegistry:
    """Tests for ServiceRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create a service registry."""
        return ServiceRegistry()

    @pytest_asyncio.fixture
    async def mock_service(self):
        """Create a mock service."""
        config = Settings()
        service = ConcreteService(config)
        yield service
        if service.is_initialized:
            await service.cleanup()

    def test_service_registration(self, registry, mock_service):
        """Test registering a service."""
        registry.register("test_service", mock_service)
        assert registry.get("test_service") is mock_service

    def test_service_not_found(self, registry):
        """Test getting a non-existent service."""
        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_initialize_all_services(self, registry, mock_service):
        """Test initializing all registered services."""
        registry.register("test_service", mock_service)

        await registry.initialize_all()

        assert mock_service.is_initialized
        await mock_service.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_all_with_failure(self, registry):
        """Test initialize_all when a service fails."""
        config = Settings()

        class FailingService(BaseService):
            async def _initialize_impl(self):
                raise RuntimeError("Init failed")

        failing_service = FailingService(config)
        registry.register("failing", failing_service)

        with pytest.raises(RuntimeError):
            await registry.initialize_all()

    @pytest.mark.asyncio
    async def test_cleanup_all_services(self, registry, mock_service):
        """Test cleaning up all services."""
        registry.register("test_service", mock_service)
        await mock_service.initialize()

        await registry.cleanup_all()

        assert not mock_service.is_healthy

    @pytest.mark.asyncio
    async def test_health_check_all(self, registry, mock_service):
        """Test health checking all services."""
        registry.register("test_service", mock_service)
        await mock_service.initialize()

        results = await registry.health_check_all()

        assert "test_service" in results
        assert results["test_service"]["healthy"] is True

        await mock_service.cleanup()

    @pytest.mark.asyncio
    async def test_health_check_all_with_error(self, registry):
        """Test health check all when service raises."""
        mock_service = MagicMock()
        mock_service.health_check = AsyncMock(side_effect=RuntimeError("Check failed"))

        registry.register("failing", mock_service)

        results = await registry.health_check_all()

        assert results["failing"]["healthy"] is False
        assert "error" in results["failing"]

    def test_get_healthy_services(self, registry):
        """Test getting healthy services."""
        config = Settings()
        service1 = ConcreteService(config)
        service2 = ConcreteService(config)

        service1._healthy = True
        service2._healthy = False

        registry.register("healthy", service1)
        registry.register("unhealthy", service2)

        healthy = registry.get_healthy_services()

        assert "healthy" in healthy
        assert "unhealthy" not in healthy

    def test_get_unhealthy_services(self, registry):
        """Test getting unhealthy services."""
        config = Settings()
        service1 = ConcreteService(config)
        service2 = ConcreteService(config)

        service1._healthy = True
        service2._healthy = False

        registry.register("healthy", service1)
        registry.register("unhealthy", service2)

        unhealthy = registry.get_unhealthy_services()

        assert "unhealthy" in unhealthy
        assert "healthy" not in unhealthy


class TestMCPService:
    """Tests for MCPService class."""

    @pytest_asyncio.fixture
    async def mcp_service(self):
        """Create an MCP service instance."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()
        yield service
        await service.cleanup()

    @pytest.mark.asyncio
    async def test_mcp_initialization(self):
        """Test MCP service initialization."""
        config = Settings()
        service = MCPService(config)

        await service.initialize()

        assert service.is_initialized
        assert service.is_healthy
        assert len(service._tools) >= 24
        assert "kb_search" in service._tools
        assert "kb_health" in service._tools

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_register_tool(self, mcp_service):
        """Test registering a tool."""
        tool = await mcp_service.register_tool("custom_tool", "Custom description")

        assert tool.name == "custom_tool"
        assert tool.description == "Custom description"
        assert tool.total_calls == 0
        assert tool.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_record_tool_call_success(self, mcp_service):
        """Test recording a successful tool call."""
        await mcp_service.record_tool_call(
            agent="test_agent",
            tool_name="kb_search",
            query="test query",
            success=True,
            response_time_ms=50.0,
        )

        tool = mcp_service._tools["kb_search"]
        assert tool.total_calls == 1
        assert tool.success_rate == 100.0
        assert "test_agent" in mcp_service._active_agents

    @pytest.mark.asyncio
    async def test_record_tool_call_failure(self, mcp_service):
        """Test recording a failed tool call."""
        await mcp_service.record_tool_call(
            agent="test_agent",
            tool_name="kb_search",
            query="test query",
            success=False,
        )

        tool = mcp_service._tools["kb_search"]
        assert tool.total_calls == 1
        assert tool.success_rate < 100.0

    @pytest.mark.asyncio
    async def test_record_multiple_tool_calls(self, mcp_service):
        """Test recording multiple tool calls."""
        for i in range(10):
            success = i % 2 == 0
            await mcp_service.record_tool_call(
                agent=f"agent_{i}",
                tool_name="kb_search",
                query=f"query_{i}",
                success=success,
            )

        tool = mcp_service._tools["kb_search"]
        assert tool.total_calls == 10
        # 5 successes out of 10
        assert tool.success_rate == 50.0

    @pytest.mark.asyncio
    async def test_get_server_status(self, mcp_service):
        """Test getting server status."""
        await mcp_service.record_tool_call("agent1", "kb_search", "query", True)

        status = await mcp_service.get_server_status()

        assert isinstance(status, MCPServerStatus)
        assert status.status == "active"
        assert len(status.tools) == len(mcp_service._tools)
        assert status.active_agents == 1
        assert status.success_rate >= 0

    @pytest.mark.asyncio
    async def test_get_tool_analytics(self, mcp_service):
        """Test getting tool analytics."""
        await mcp_service.record_tool_call("agent1", "kb_search", "query1", True)
        await mcp_service.record_tool_call("agent1", "kb_search", "query2", True)
        await mcp_service.record_tool_call("agent2", "kb_stats", "query3", False)

        analytics = await mcp_service.get_tool_analytics()
        assert analytics["total_tools"] == len(mcp_service._tools)
        assert analytics["total_calls"] == 3
        assert len(analytics["tool_usage_ranking"]) > 0
        assert len(analytics["most_used_tools"]) > 0
        assert "agent1" in analytics["agent_activity"]
        assert "agent2" in analytics["agent_activity"]

    @pytest.mark.asyncio
    async def test_get_agent_list(self, mcp_service):
        """Test getting agent list."""
        await mcp_service.record_tool_call("agent1", "kb_search", "query1", True)
        await mcp_service.record_tool_call("agent1", "kb_search", "query2", False)
        await mcp_service.record_tool_call("agent2", "kb_stats", "query3", True)

        agents = await mcp_service.get_agent_list()

        assert len(agents) == 2
        agent_names = [a["name"] for a in agents]
        assert "agent1" in agent_names
        assert "agent2" in agent_names

        agent1 = next(a for a in agents if a["name"] == "agent1")
        assert agent1["total_calls"] == 2
        assert agent1["success_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_cleanup_old_activity(self, mcp_service):
        """Test cleaning up old activity records."""
        # Add some activity
        await mcp_service.record_tool_call("agent1", "kb_search", "query1", True)

        # Cleanup with 0 hours (should remove all)
        removed = await mcp_service.cleanup_old_activity(hours=0)

        assert removed == 1
        assert len(mcp_service._recent_activity) == 0

    @pytest.mark.asyncio
    async def test_reset_tool_stats(self, mcp_service):
        """Test resetting tool statistics."""
        await mcp_service.record_tool_call("agent1", "kb_search", "query1", True)
        assert mcp_service._tools["kb_search"].total_calls == 1

        result = await mcp_service.reset_tool_stats("kb_search")

        assert result is True
        assert mcp_service._tools["kb_search"].total_calls == 0
        assert mcp_service._tools["kb_search"].success_rate == 100.0

    @pytest.mark.asyncio
    async def test_reset_nonexistent_tool_stats(self, mcp_service):
        """Test resetting stats for a non-existent tool."""
        result = await mcp_service.reset_tool_stats("nonexistent_tool")
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_health_check(self, mcp_service):
        """Test MCP custom health check."""
        health = await mcp_service._custom_health_check()

        assert "registered_tools" in health
        assert health["registered_tools"] == len(mcp_service._tools)
        assert "active_agents" in health
        assert "recent_activity_count" in health
        assert "uptime_seconds" in health

    def test_uptime_tracking(self):
        """Test uptime calculation."""
        config = Settings()
        service = MCPService(config)

        time.sleep(0.05)

        uptime = service._get_uptime_seconds()
        assert uptime > 0.04

    @pytest.mark.asyncio
    async def test_hourly_request_tracking(self, mcp_service):
        """Test hourly request tracking."""
        await mcp_service.record_tool_call("agent1", "kb_search", "query1", True)
        await mcp_service.record_tool_call("agent1", "kb_search", "query2", True)

        status = await mcp_service.get_server_status()
        assert status.requests_per_hour >= 2


class TestSystemMonitoringService:
    """Tests for SystemMonitoringService class."""

    @pytest_asyncio.fixture
    async def system_service(self):
        """Create a system monitoring service."""
        config = Settings()
        service = SystemMonitoringService(config)
        await service.initialize()
        yield service
        await service.cleanup()

    @pytest.mark.asyncio
    async def test_system_service_initialization(self):
        """Test system service initialization."""
        config = Settings()
        service = SystemMonitoringService(config)

        await service.initialize()

        assert service.is_initialized
        assert service.is_healthy

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_get_system_stats(self, system_service):
        """Test getting system statistics."""
        stats = await system_service.get_system_stats()

        assert stats.total_documents == 0
        assert stats.total_indices == 0
        assert stats.total_searches == 0
        assert stats.memory_usage_mb > 0
        assert stats.storage_usage_gb >= 0

    @pytest.mark.asyncio
    async def test_get_system_stats_with_storage_backend(self):
        """Test system stats with storage backend."""
        config = Settings()
        mock_storage = AsyncMock()
        mock_storage.list_indices = AsyncMock(return_value=[])

        service = SystemMonitoringService(config, storage_backend=mock_storage)
        await service.initialize()

        stats = await service.get_system_stats()
        assert isinstance(stats.total_documents, int)

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_get_system_stats_uses_local_indices_size(self, tmp_path):
        """Local backend stats should report indices tree size, not whole FS used."""
        from knowledgebase.core.models import Document, DocumentMetadata
        from knowledgebase.storage.local import LocalStorageBackend

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()
        await backend.add_document(
            Document(
                id="doc-1",
                content="hello storage size",
                embedding=None,
                index_name="kb",
                metadata=DocumentMetadata(title="t"),
            )
        )

        config = Settings()
        service = SystemMonitoringService(config, storage_backend=backend)
        await service.initialize()

        stats = await service.get_system_stats()
        expected_gb = (await backend.get_storage_usage_bytes()) / (1024 * 1024 * 1024)
        assert stats.total_documents == 1
        assert stats.total_indices == 1
        assert abs(stats.storage_usage_gb - expected_gb) < 1e-9

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_get_performance_metrics(self, system_service):
        """Test getting performance metrics."""
        metrics = await system_service.get_performance_metrics()

        assert metrics.cpu_usage >= 0
        assert metrics.memory_usage.used_gb >= 0
        assert metrics.storage_usage.used_gb >= 0
        assert metrics.network_throughput >= 0
        assert metrics.disk_io_read_mb_s >= 0
        assert metrics.disk_io_write_mb_s >= 0

    @pytest.mark.asyncio
    async def test_get_service_status_list(self, system_service):
        """Test getting service status list."""
        services = await system_service.get_service_status_list()

        assert len(services) > 0
        assert any(s.name == "KnowledgeBase API" for s in services)
        assert any(s.name == "MCP Server Endpoint" for s in services)

    @pytest.mark.asyncio
    async def test_get_docker_status_native(self, system_service):
        """Test docker status detection (native environment)."""
        status = await system_service.get_docker_status()

        assert "running_in_docker" in status
        assert isinstance(status["running_in_docker"], bool)

    @pytest.mark.asyncio
    async def test_get_system_info(self, system_service, monkeypatch):
        """Test getting system info."""
        # Unit test: do not require privileged host sysctl access on macOS.
        from types import SimpleNamespace

        monkeypatch.setattr("knowledgebase.services.system_service.psutil.boot_time", lambda: 0)
        monkeypatch.setattr(
            "knowledgebase.services.system_service.psutil.cpu_count", lambda logical=True: 2
        )
        monkeypatch.setattr(
            "knowledgebase.services.system_service.psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )
        info = await system_service.get_system_info()

        assert "system_uptime_seconds" in info
        assert "cpu_count_logical" in info
        assert "cpu_count_physical" in info
        assert "memory_total_gb" in info
        assert info["cpu_count_logical"] > 0

    def test_increment_search_count(self, system_service):
        """Test incrementing search count."""
        assert system_service._search_count == 0

        system_service.increment_search_count()
        assert system_service._search_count == 1

        system_service.increment_search_count()
        assert system_service._search_count == 2

    @pytest.mark.asyncio
    async def test_custom_health_check(self, system_service):
        """Test system service custom health check."""
        health = await system_service._custom_health_check()

        assert "psutil_available" in health
        assert health["psutil_available"] is True
        assert "uptime_seconds" in health

    @pytest.mark.asyncio
    async def test_get_system_stats_with_storage_error(self):
        """Test system stats handles storage errors gracefully."""
        config = Settings()
        mock_storage = AsyncMock()
        mock_storage.list_indices = AsyncMock(side_effect=RuntimeError("Storage error"))

        service = SystemMonitoringService(config, storage_backend=mock_storage)
        await service.initialize()

        stats = await service.get_system_stats()
        assert stats.total_documents == 0

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_get_service_status_with_storage_error(self):
        """Test service status handles storage errors gracefully."""
        config = Settings()
        mock_storage = AsyncMock()
        mock_storage.health_check = AsyncMock(side_effect=RuntimeError("Storage error"))

        service = SystemMonitoringService(config, storage_backend=mock_storage)
        await service.initialize()

        services = await service.get_service_status_list()
        storage_status = next((s for s in services if s.name == "Storage Backend"), None)
        assert storage_status is not None
        assert storage_status.status == "unhealthy"

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_ensure_initialized_check(self):
        """Test that methods check initialization."""
        uninitialized_service = SystemMonitoringService(Settings())

        with pytest.raises(RuntimeError):
            await uninitialized_service.get_system_stats()

        with pytest.raises(RuntimeError):
            await uninitialized_service.get_performance_metrics()

        with pytest.raises(RuntimeError):
            await uninitialized_service.get_service_status_list()


class TestServiceInteractions:
    """Tests for service interactions and edge cases."""

    @pytest.mark.asyncio
    async def test_multiple_service_initialization(self):
        """Test initializing multiple services."""
        config = Settings()
        registry = ServiceRegistry()

        service1 = ConcreteService(config)
        service2 = MCPService(config)
        service3 = SystemMonitoringService(config)

        registry.register("concrete", service1)
        registry.register("mcp", service2)
        registry.register("system", service3)

        await registry.initialize_all()

        assert all(s.is_initialized for s in [service1, service2, service3])

        await registry.cleanup_all()

        assert not any(s.is_healthy for s in [service1, service2, service3])

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self):
        """Test handling concurrent tool calls."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()

        # Create multiple concurrent calls
        tasks = [
            service.record_tool_call(
                agent=f"agent_{i % 3}",
                tool_name="kb_search",
                query=f"query_{i}",
                success=i % 2 == 0,
            )
            for i in range(20)
        ]

        await asyncio.gather(*tasks)

        assert service._tools["kb_search"].total_calls == 20

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_activity_deque_maxlen(self):
        """Test that activity deque respects maxlen."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()

        # Add more activities than maxlen (100)
        for i in range(150):
            await service.record_tool_call(
                agent="agent",
                tool_name="kb_search",
                query=f"query_{i}",
            )

        assert len(service._recent_activity) == 100

        await service.cleanup()


class TestSystemServiceEdgeCases:
    """Tests for SystemMonitoringService edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_system_service_initialization_with_psutil_error(self):
        """Test system service handles psutil initialization errors."""
        config = Settings()
        service = SystemMonitoringService(config)

        with (
            patch("psutil.cpu_percent", side_effect=RuntimeError("psutil error")),
            pytest.raises(RuntimeError),
        ):
            await service.initialize()

    @pytest.mark.asyncio
    async def test_get_system_stats_error(self):
        """Test system stats error handling."""
        config = Settings()
        service = SystemMonitoringService(config)
        await service.initialize()

        with (
            patch("psutil.virtual_memory", side_effect=RuntimeError("Memory error")),
            pytest.raises(RuntimeError),
        ):
            await service.get_system_stats()

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_get_performance_metrics_error(self):
        """Test performance metrics error handling."""
        config = Settings()
        service = SystemMonitoringService(config)
        await service.initialize()

        with (
            patch("psutil.cpu_percent", side_effect=RuntimeError("CPU error")),
            pytest.raises(RuntimeError),
        ):
            await service.get_performance_metrics()

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_performance_metrics_network_stats_none(self):
        """Test performance metrics with None network stats."""
        config = Settings()
        service = SystemMonitoringService(config)
        await service.initialize()

        service._last_network_stats = None
        service._last_disk_stats = None

        metrics = await service.get_performance_metrics()
        assert metrics.network_throughput == 0.0
        assert metrics.disk_io_read_mb_s == 0.0
        assert metrics.disk_io_write_mb_s == 0.0

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_service_status_with_working_storage(self):
        """Test service status list with working storage backend."""
        config = Settings()
        mock_storage = AsyncMock()
        mock_storage.health_check = AsyncMock(
            return_value={"healthy": True, "backend_type": "local"}
        )

        service = SystemMonitoringService(config, storage_backend=mock_storage)
        await service.initialize()

        services = await service.get_service_status_list()
        storage_service = next((s for s in services if s.name == "Storage Backend"), None)
        assert storage_service is not None
        assert storage_service.status == "healthy"

        await service.cleanup()

    def test_uptime_calculation(self):
        """Test uptime calculation in system service."""
        config = Settings()
        service = SystemMonitoringService(config)

        initial_uptime = service._get_uptime_seconds()
        assert initial_uptime >= 0

        time.sleep(0.05)
        later_uptime = service._get_uptime_seconds()
        assert later_uptime > initial_uptime

    @pytest.mark.asyncio
    async def test_mcp_record_tool_call_with_unregistered_tool(self):
        """Test recording tool call for unregistered tool."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()

        await service.record_tool_call(
            agent="agent",
            tool_name="unregistered_tool",
            query="query",
            success=True,
        )

        assert len(service._recent_activity) == 1

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_mcp_tool_call_success_rate_tracking(self):
        """Test that success rate tracking maintains reasonable size."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()

        for i in range(150):
            await service.record_tool_call(
                agent="agent",
                tool_name="kb_search",
                query=f"query_{i}",
                success=i % 3 == 0,
            )

        assert len(service._tool_call_success["kb_search"]) <= 100

        await service.cleanup()

    @pytest.mark.asyncio
    async def test_mcp_get_server_status_empty_state(self):
        """Test getting server status with no activity."""
        config = Settings()
        service = MCPService(config)
        await service.initialize()

        status = await service.get_server_status()

        assert status.status == "active"
        assert status.active_agents == 0
        assert len(status.recent_activity) == 0
        assert status.success_rate == 100.0

        await service.cleanup()
