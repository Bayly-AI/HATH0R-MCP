"""
Status monitoring service for comprehensive MCP health checks and diagnostics.

Provides comprehensive testing of MCP tools, API endpoints, and system statistics.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from knowledgebase.core.config import Settings
from knowledgebase.core.models import (
    AggregateStats,
    DiagnosticIssue,
    DiagnosticReport,
    EndpointTestResult,
    FullStatusResponse,
    SyncStatusInfo,
    ToolTestResult,
)
from knowledgebase.services.base import BaseService

logger = structlog.get_logger(__name__)


class StatusService(BaseService):
    """
    Service for comprehensive MCP health checks and system diagnostics.

    Tests all MCP tools, API endpoints, and aggregates system statistics.
    """

    def __init__(self, config: Settings) -> None:
        """Initialize the status service."""
        super().__init__(config)
        self._base_url = self._resolve_base_url(config)
        self._startup_time = time.time()

    @staticmethod
    def _resolve_base_url(config: Settings) -> str:
        """Resolve the API base URL used for status probes."""
        explicit_base = os.getenv("KB_STATUS_BASE_URL", "").strip()
        if explicit_base:
            return explicit_base.rstrip("/")
        explicit_port = os.getenv("KB_API_PORT", "").strip() or os.getenv("PORT", "").strip()

        host = str(config.api_host).strip() if config.api_host else "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        if host.count(":") > 1 and not host.startswith("["):
            host = f"[{host}]"

        if host.startswith(("http://", "https://")):  # NOSONAR scheme check, not a network call
            return host.rstrip("/")
        port = config.api_port
        if explicit_port:
            try:
                port = int(explicit_port)
            except ValueError:
                port = config.api_port

        return f"http://{host}:{port}"  # NOSONAR local dev default; no TLS listener on localhost

    async def _initialize_impl(self) -> None:
        """Initialize status service."""
        self.logger.info("Status monitoring service initialized")

    async def _custom_health_check(self) -> dict[str, Any]:
        """Custom health check for status service."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return {
                    "api_accessible": response.status_code == 200,
                    "uptime_seconds": self._get_uptime_seconds(),
                }
        except Exception as e:
            return {"api_accessible": False, "error": str(e)}

    def _get_uptime_seconds(self) -> float:
        """Get service uptime in seconds."""
        return time.time() - self._startup_time

    async def test_all_mcp_tools(self) -> dict[str, ToolTestResult]:
        """
        Test all core MCP tools with safe, read-only operations.

        Returns:
            Dictionary mapping tool names to test results.
        """
        self._ensure_initialized()

        results: dict[str, ToolTestResult] = {}
        tools_to_test = [
            "kb_health",
            "kb_stats",
            "kb_index_list",
            "kb_taxonomy_list",
            "docs_kb_info",
            "docs_list_dirs",
            "runbook_list",
            "kb_embedding_info",
            "kb_rag_config_get",
            "kb_search_config_get",
            "infraos_ping",
            "infraos_context",
            "infraos_env_list",
        ]

        for tool_name in tools_to_test:
            start_time = time.time()
            try:
                result, error_message = await self._test_mcp_tool(tool_name)
                duration_ms = (time.time() - start_time) * 1000

                results[tool_name] = ToolTestResult(
                    name=tool_name,
                    status="pass" if result else "fail",
                    duration_ms=duration_ms,
                    error_message=None if result else (error_message or "No response"),
                )
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                results[tool_name] = ToolTestResult(
                    name=tool_name,
                    status="fail",
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
                self.logger.warning(f"Tool test failed: {tool_name}", error=str(e))

        return results

    async def test_all_api_endpoints(self) -> dict[str, EndpointTestResult]:
        """
        Test all critical API endpoints.

        Returns:
            Dictionary mapping endpoint paths to test results.
        """
        self._ensure_initialized()

        results: dict[str, EndpointTestResult] = {}
        endpoints = [
            ("GET", "/health"),
            ("GET", "/api/v1/runtime/status"),
            ("GET", "/api/v1/system/stats"),
            ("GET", "/api/v1/system/performance"),
            ("GET", "/api/v1/system/services"),
            ("GET", "/api/v1/indices"),
            ("GET", "/api/v1/rag/config"),
            ("POST", "/api/v1/search"),
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for method, path in endpoints:
                start_time = time.time()
                try:
                    url = f"{self._base_url}{path}"

                    if method == "GET":
                        response = await client.get(url)
                    else:  # POST
                        # Send a test search query
                        response = await client.post(
                            url,
                            json={"query": "test", "limit": 1},
                        )

                    duration_ms = (time.time() - start_time) * 1000
                    results[path] = EndpointTestResult(
                        path=path,
                        method=method,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                        error=None if response.status_code < 400 else response.text[:200],
                    )

                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000
                    results[path] = EndpointTestResult(
                        path=path,
                        method=method,
                        status_code=None,
                        duration_ms=duration_ms,
                        error=str(e)[:200],
                    )
                    self.logger.warning(f"Endpoint test failed: {path}", error=str(e))

        return results

    async def get_sync_status(self) -> SyncStatusInfo:
        """
        Get status of last sync operation.

        Returns:
            SyncStatusInfo with last sync details.
        """
        self._ensure_initialized()

        try:
            status_paths = [
                self.config.config_dir / "status.json",
                self.config.data_dir / "status.json",
            ]
            best_status: SyncStatusInfo | None = None
            best_timestamp: datetime | None = None
            for status_file in status_paths:
                if not status_file.exists():
                    continue
                content = status_file.read_text()
                data = json.loads(content)
                last_sync_value = data.get("last_sync") or data.get("last_sync_time")
                last_sync_time: datetime | None = None
                if isinstance(last_sync_value, str) and last_sync_value.strip():
                    try:
                        parsed = datetime.fromisoformat(last_sync_value)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        last_sync_time = parsed
                    except ValueError:
                        self.logger.warning(
                            "Failed to parse last_sync timestamp",
                            path=str(status_file),
                            last_sync=last_sync_value,
                        )
                candidate_status = SyncStatusInfo(
                    last_sync_time=last_sync_time,
                    sync_duration_seconds=data.get("sync_duration_seconds", 0.0),
                    indices_synced=data.get("indices_synced", 0),
                    documents_synced=data.get("documents_synced", 0),
                    sync_errors=data.get("sync_errors", []),
                )
                candidate_timestamp = (
                    last_sync_time
                    if last_sync_time is not None
                    else datetime.fromtimestamp(status_file.stat().st_mtime, timezone.utc)
                )
                if best_timestamp is None or candidate_timestamp > best_timestamp:
                    best_timestamp = candidate_timestamp
                    best_status = candidate_status
            if best_status is not None:
                return best_status
        except Exception as e:
            self.logger.warning("Failed to read sync status", error=str(e))

        return SyncStatusInfo()

    async def get_aggregate_stats(self) -> AggregateStats:
        """
        Get aggregate system statistics.

        Returns:
            AggregateStats with current metrics.
        """
        self._ensure_initialized()

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Get system stats
                response = await client.get(f"{self._base_url}/api/v1/system/stats")
                if response.status_code == 200:
                    stats_data = response.json()
                else:
                    self.logger.warning(f"Failed to get system stats: {response.status_code}")
                    stats_data = {}

                uptime_seconds = stats_data.get("uptime_seconds", 0.0)
                uptime_formatted = self._format_uptime(uptime_seconds)

                return AggregateStats(
                    total_documents=stats_data.get("total_documents", 0),
                    total_indices=stats_data.get("total_indices", 0),
                    total_runbooks=0,  # TODO: Get from runbook service
                    total_rules=0,  # TODO: Count rule documents
                    uptime_seconds=uptime_seconds,
                    uptime_formatted=uptime_formatted,
                    last_interaction_ago=self._format_time_ago(datetime.now(timezone.utc)),
                    memory_usage_mb=stats_data.get("memory_usage_mb", 0.0),
                    storage_usage_gb=stats_data.get("storage_usage_gb", 0.0),
                    search_count=stats_data.get("total_searches", 0),
                )
        except Exception as e:
            self.logger.warning("Failed to get aggregate stats", error=str(e))
            return AggregateStats()

    async def generate_diagnostic_report(
        self, tools: dict[str, ToolTestResult], endpoints: dict[str, EndpointTestResult]
    ) -> DiagnosticReport:
        """
        Generate a diagnostic report from test results.

        Args:
            tools: Results from testing MCP tools.
            endpoints: Results from testing API endpoints.

        Returns:
            DiagnosticReport with issues and recommendations.
        """
        start_time = time.time()
        issues: list[DiagnosticIssue] = []
        recommendations: list[str] = []

        # Check tool results
        tools_passed = sum(1 for r in tools.values() if r.status == "pass")
        tools_failed = sum(1 for r in tools.values() if r.status == "fail")

        if tools_failed > 0:
            issues.append(
                DiagnosticIssue(
                    severity="warning",
                    component="MCP Tools",
                    message=f"{tools_failed} MCP tool(s) failed",
                    recommendation="Check tool availability and error logs",
                )
            )
            recommendations.append("Review failed tool errors in detailed report")

        # Check endpoint results
        endpoints_passed = sum(
            1 for r in endpoints.values() if isinstance(r.status_code, int) and r.status_code < 400
        )
        endpoints_failed = len(endpoints) - endpoints_passed

        if endpoints_failed > 0:
            issues.append(
                DiagnosticIssue(
                    severity="warning",
                    component="API Endpoints",
                    message=f"{endpoints_failed} API endpoint(s) returned errors",
                    recommendation="Check API server logs and database connectivity",
                )
            )
            recommendations.append("Verify API server health and external dependencies")

        # Check performance
        avg_tool_time = sum(r.duration_ms for r in tools.values()) / len(tools) if tools else 0

        if avg_tool_time > 1000:  # > 1 second
            issues.append(
                DiagnosticIssue(
                    severity="info",
                    component="Performance",
                    message=f"Average tool response time is {avg_tool_time:.0f}ms (high)",
                    recommendation="Check system resources and network latency",
                )
            )

        duration_ms = (time.time() - start_time) * 1000

        return DiagnosticReport(
            duration_ms=duration_ms,
            tools_passed=tools_passed,
            tools_failed=tools_failed,
            endpoints_passed=endpoints_passed,
            endpoints_failed=endpoints_failed,
            issues=issues,
            recommendations=recommendations,
        )

    async def get_full_status(self) -> FullStatusResponse:
        """
        Get comprehensive status of all MCP components.

        Returns:
            FullStatusResponse with complete diagnostics.
        """
        self._ensure_initialized()

        # Test all components in parallel
        tools_task = self.test_all_mcp_tools()
        endpoints_task = self.test_all_api_endpoints()
        sync_task = self.get_sync_status()
        stats_task = self.get_aggregate_stats()

        tools, endpoints, sync_status, stats = await asyncio.gather(
            tools_task, endpoints_task, sync_task, stats_task
        )

        # Generate diagnostic report
        diagnostics = await self.generate_diagnostic_report(tools, endpoints)
        if sync_status.last_sync_time is None and stats.total_documents > 0:
            diagnostics.issues.append(
                DiagnosticIssue(
                    severity="warning",
                    component="Sync",
                    message="Sync has never run while documents exist",
                    recommendation="Run initial sync/bootstrap and verify scheduler wiring",
                )
            )
            diagnostics.recommendations.append(
                "Initialize sync state so last_sync_time is populated and monitored."
            )

        # Determine overall status
        tools_healthy = all(r.status == "pass" for r in tools.values())
        endpoints_healthy = all(
            isinstance(r.status_code, int) and r.status_code < 400 for r in endpoints.values()
        )
        overall_status = "healthy" if tools_healthy and endpoints_healthy else "degraded"

        return FullStatusResponse(
            overall_status=overall_status,
            tools=list(tools.values()),
            endpoints=list(endpoints.values()),
            sync=sync_status,
            stats=stats,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _tool_test_arguments(tool_name: str) -> dict[str, Any]:
        """Return safe arguments for tool smoke tests."""
        argument_map: dict[str, dict[str, Any]] = {
            "aegis_echo": {"message": "status-check"},
            "aegis_env_get": {"name": "PATH"},
            "aegis_env_list": {"prefix": "KB_", "values": False},
            "infraos_echo": {"message": "status-check"},
            "infraos_env_get": {"name": "PATH"},
            "infraos_env_list": {"prefix": "KB_", "values": False},
        }
        return argument_map.get(tool_name, {})

    async def _test_mcp_tool(self, tool_name: str) -> tuple[bool, str | None]:
        """
        Test a single MCP tool.

        Args:
            tool_name: Name of the tool to test.

        Returns:
            Tuple of (success, optional error message).
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "jsonrpc": "2.0",
                    "id": f"status-{tool_name}",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": self._tool_test_arguments(tool_name),
                    },
                }
                response = await client.post(f"{self._base_url}/mcp/sse", json=payload)
                if response.status_code != 200:
                    return False, f"HTTP {response.status_code}"

                rpc_payload: Any | None = None
                try:
                    parsed = response.json()
                    if asyncio.iscoroutine(parsed):
                        parsed = await parsed
                    rpc_payload = parsed
                except Exception:
                    rpc_payload = None

                if isinstance(rpc_payload, dict):
                    rpc_error = rpc_payload.get("error")
                    if isinstance(rpc_error, dict):
                        message = rpc_error.get("message")
                        return (
                            False,
                            str(message) if isinstance(message, str) else "JSON-RPC error",
                        )
                    rpc_result = rpc_payload.get("result")
                    if isinstance(rpc_result, dict) and rpc_result.get("isError") is True:
                        content = rpc_result.get("content")
                        if isinstance(content, list) and content and isinstance(content[0], dict):
                            content_text = content[0].get("text")
                            if isinstance(content_text, str):
                                return False, content_text
                        return False, "Tool returned isError=true"
                return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d {hours}h"

    @staticmethod
    def _format_time_ago(timestamp: datetime) -> str:
        """Format time difference as human-readable string."""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - timestamp
        seconds = diff.total_seconds()

        if seconds < 60:
            return "now"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        else:
            return f"{int(seconds // 86400)}d ago"
