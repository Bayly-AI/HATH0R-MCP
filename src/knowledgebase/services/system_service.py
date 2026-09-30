"""
System monitoring service for collecting system metrics and performance data.

Uses psutil to gather CPU, memory, disk, and network statistics.
"""

from __future__ import annotations


import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from knowledgebase.core.config import Settings
from knowledgebase.core.models import (
    MemoryUsage,
    PerformanceMetrics,
    ServiceStatus,
    StorageUsage,
    SystemStats,
)
from knowledgebase.services.base import BaseService
from knowledgebase.storage.base import StorageBackend
from knowledgebase.storage.local import LocalStorageBackend

VECTOR_EMBEDDINGS_LABEL = "Vector Embeddings"


class SystemMonitoringService(BaseService):
    """
    Service for monitoring system resources and performance metrics.

    Collects real-time data about CPU usage, memory consumption,
    disk I/O, network activity, and service health.
    """

    def __init__(
        self,
        config: Settings,
        storage_backend: StorageBackend | None = None,
        embedding_provider: Any | None = None,
    ) -> None:
        """
        Initialize the system monitoring service.

        Args:
            config: Application configuration settings.
            storage_backend: Optional storage backend for document statistics.
            embedding_provider: Optional embedding provider for health checks.
        """
        super().__init__(config)
        self.storage_backend = storage_backend
        self.embedding_provider = embedding_provider
        self._start_time = time.time()
        self._search_count = 0
        self._last_network_stats = None
        self._last_disk_stats = None
        self._stats_timestamp = time.time()

    async def _initialize_impl(self) -> None:
        """Initialize system monitoring service."""
        # Test psutil access to ensure we can collect metrics
        try:
            psutil.cpu_percent()  # Initialize CPU monitoring
            psutil.virtual_memory()
            psutil.disk_usage("/")

            # Initialize network and disk stats for delta calculations
            self._last_network_stats = psutil.net_io_counters()
            self._last_disk_stats = psutil.disk_io_counters()
            self._stats_timestamp = time.time()

            self.logger.info("System monitoring service initialized successfully")
        except Exception as e:
            self.logger.error("Failed to initialize system monitoring", error=str(e))
            raise

    async def _custom_health_check(self) -> dict[str, Any]:
        """Custom health check for system monitoring service."""
        try:
            # Quick system access test - calls raise into the except block below
            # on failure, so a successful call always means the check passed.
            psutil.cpu_percent(interval=0.1)
            psutil.virtual_memory()

            return {
                "psutil_available": True,
                "cpu_accessible": True,
                "memory_accessible": True,
                "uptime_seconds": self._get_uptime_seconds(),
            }
        except Exception as e:
            return {
                "psutil_available": False,
                "error": str(e),
            }

    def _get_uptime_seconds(self) -> float:
        """Get service uptime in seconds."""
        return time.time() - self._start_time

    async def get_system_stats(self) -> SystemStats:
        """
        Get current system statistics.

        Returns:
            SystemStats object with current metrics.
        """
        self._ensure_initialized()

        try:
            # Get document and index counts from storage if available
            total_documents = 0
            total_indices = 0

            if self.storage_backend:
                try:
                    indices = await self.storage_backend.list_indices()
                    total_indices = len(indices)
                    total_documents = sum(idx.document_count for idx in indices)
                except Exception as e:
                    self.logger.warning("Failed to get storage stats", error=str(e))

            # Get memory usage
            memory = psutil.virtual_memory()
            memory_usage_mb = memory.used / (1024 * 1024)

            # Prefer on-disk size of the local indices tree (what AegisCMCP stores)
            # over filesystem-wide ``disk_usage.used``, which reports the whole
            # volume and misleads compliance (e.g. ~194GB FS used vs ~62GB indices).
            storage_usage_gb = await self._resolve_storage_usage_gb()

            return SystemStats(
                total_documents=total_documents,
                total_indices=total_indices,
                total_searches=self._search_count,
                uptime_seconds=self._get_uptime_seconds(),
                memory_usage_mb=memory_usage_mb,
                storage_usage_gb=storage_usage_gb,
                active_connections=0,  # TODO: Track active API connections
            )

        except Exception as e:
            self.logger.error("Failed to get system stats", error=str(e))
            raise

    async def _resolve_storage_usage_gb(self) -> float:
        """Resolve storage usage in GB for system stats.

        Local backend: bytes under the indices path (cached).
        Fallback: filesystem used space for cwd (legacy behavior).
        """
        if isinstance(self.storage_backend, LocalStorageBackend):
            try:
                size_bytes = await self.storage_backend.get_storage_usage_bytes()
                return size_bytes / (1024 * 1024 * 1024)
            except Exception as e:  # noqa: BLE001
                self.logger.warning(
                    "Failed to measure local indices size; falling back to filesystem used",
                    error=str(e),
                )

        probe_path = Path.cwd()
        if isinstance(self.storage_backend, LocalStorageBackend):
            probe_path = self.storage_backend.base_path
        try:
            disk_usage = psutil.disk_usage(str(probe_path))
            return disk_usage.used / (1024 * 1024 * 1024)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Failed to read filesystem disk usage", error=str(e))
            return 0.0

    async def get_performance_metrics(self) -> PerformanceMetrics:
        """
        Get detailed performance metrics.

        Returns:
            PerformanceMetrics object with current performance data.
        """
        self._ensure_initialized()

        try:
            # CPU usage (get average over 0.5 seconds for accuracy)
            cpu_percent = await self._safe_execute(
                "get_cpu_percent", psutil.cpu_percent, interval=0.5
            )

            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage = MemoryUsage(
                used_gb=memory.used / (1024 * 1024 * 1024),
                total_gb=memory.total / (1024 * 1024 * 1024),
                percentage=memory.percent,
            )

            # Storage usage
            disk_usage = psutil.disk_usage(str(Path.cwd()))
            storage_usage = StorageUsage(
                used_gb=disk_usage.used / (1024 * 1024 * 1024),
                total_gb=disk_usage.total / (1024 * 1024 * 1024),
                percentage=(disk_usage.used / disk_usage.total) * 100,
            )

            # Network throughput (calculate delta)
            network_throughput = 0.0
            current_network = psutil.net_io_counters()
            current_time = time.time()

            if self._last_network_stats:
                time_delta = current_time - self._stats_timestamp
                if time_delta > 0:
                    bytes_sent_delta = (
                        current_network.bytes_sent - self._last_network_stats.bytes_sent
                    )
                    bytes_recv_delta = (
                        current_network.bytes_recv - self._last_network_stats.bytes_recv
                    )
                    total_bytes_delta = bytes_sent_delta + bytes_recv_delta
                    network_throughput = (total_bytes_delta / time_delta) / (1024 * 1024)  # MB/s

            # Disk I/O rates
            disk_io_read_mb_s = 0.0
            disk_io_write_mb_s = 0.0
            current_disk = psutil.disk_io_counters()

            if current_disk and self._last_disk_stats:
                time_delta = current_time - self._stats_timestamp
                if time_delta > 0:
                    read_bytes_delta = current_disk.read_bytes - self._last_disk_stats.read_bytes
                    write_bytes_delta = current_disk.write_bytes - self._last_disk_stats.write_bytes
                    disk_io_read_mb_s = (read_bytes_delta / time_delta) / (1024 * 1024)
                    disk_io_write_mb_s = (write_bytes_delta / time_delta) / (1024 * 1024)

            # Update cached stats
            self._last_network_stats = current_network
            self._last_disk_stats = current_disk
            self._stats_timestamp = current_time

            return PerformanceMetrics(
                cpu_usage=cpu_percent,
                memory_usage=memory_usage,
                storage_usage=storage_usage,
                network_throughput=network_throughput,
                disk_io_read_mb_s=disk_io_read_mb_s,
                disk_io_write_mb_s=disk_io_write_mb_s,
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            self.logger.error("Failed to get performance metrics", error=str(e))
            raise

    async def get_service_status_list(self) -> list[ServiceStatus]:
        """
        Get status of various services and components.

        Returns:
            List of ServiceStatus objects for different system components.
        """
        self._ensure_initialized()

        services = []

        try:
            # KnowledgeBase API service
            services.append(
                ServiceStatus(
                    name="KnowledgeBase API",
                    status="healthy",
                    url="http://localhost:8083",
                    port=8083,
                    uptime="99.98%",
                    response_time_ms=50.0,
                )
            )

            # MCP Server endpoint
            services.append(
                ServiceStatus(
                    name="MCP Server Endpoint",
                    status="active",
                    url="http://localhost:8083/mcp",
                    port=8083,
                    uptime="99.95%",
                    response_time_ms=25.0,
                )
            )

            # Storage backend status
            if self.storage_backend:
                try:
                    health = await self.storage_backend.health_check()
                    status = "healthy" if health.get("healthy", False) else "degraded"
                    services.append(
                        ServiceStatus(
                            name="Storage Backend",
                            status=status,
                            url=health.get("backend_type", "Unknown"),
                            uptime="99.99%",
                            response_time_ms=15.0,
                        )
                    )
                except Exception:
                    services.append(
                        ServiceStatus(
                            name="Storage Backend",
                            status="unhealthy",
                            url="Error",
                            response_time_ms=0.0,
                        )
                    )

            # Vector Embeddings service - perform actual health check
            if self.embedding_provider:
                try:
                    embedding_health = await self.embedding_provider.health_check()
                    status = "healthy" if embedding_health.get("healthy", False) else "degraded"
                    provider_name = embedding_health.get("provider", "Unknown").capitalize()
                    model_name = embedding_health.get("model", "Unknown")
                    latency_ms = embedding_health.get("latency_ms", 0.0)

                    services.append(
                        ServiceStatus(
                            name=VECTOR_EMBEDDINGS_LABEL,
                            status=status,
                            url=f"{provider_name} ({model_name})",
                            port=443,
                            uptime="99.92%",
                            response_time_ms=latency_ms,
                        )
                    )

                    if not embedding_health.get("healthy", False):
                        error_msg = embedding_health.get("error", "Unknown error")
                        self.logger.warning(
                            "Vector Embeddings service health check failed",
                            provider=embedding_health.get("provider"),
                            error=error_msg,
                        )
                except Exception as e:
                    self.logger.error("Failed to check embeddings health", error=str(e))
                    services.append(
                        ServiceStatus(
                            name=VECTOR_EMBEDDINGS_LABEL,
                            status="unhealthy",
                            url="Error",
                            port=443,
                            response_time_ms=0.0,
                        )
                    )
            else:
                # Fallback if embeddings provider not available
                services.append(
                    ServiceStatus(
                        name=VECTOR_EMBEDDINGS_LABEL,
                        status="degraded",
                        url="Not Configured",
                        port=443,
                        response_time_ms=0.0,
                    )
                )

        except Exception as e:
            self.logger.error("Failed to get service status", error=str(e))

        return services

    def increment_search_count(self) -> None:
        """Increment the search counter."""
        self._search_count += 1

    async def get_docker_status(self) -> dict[str, Any]:
        """
        Get Docker container status information.

        Returns:
            Dictionary with Docker-related status information.
        """
        try:
            # Check if running in Docker by looking for container-specific files
            is_docker = (
                Path("/.dockerenv").exists()
                or Path("/proc/1/cgroup").exists()
                and "docker" in Path("/proc/1/cgroup").read_text()
            )

            # Get container ID if running in Docker
            container_id = None
            if is_docker and Path("/proc/self/cgroup").exists():
                try:
                    cgroup_content = Path("/proc/self/cgroup").read_text()
                    for line in cgroup_content.split("\n"):
                        if "docker" in line:
                            container_id = line.split("/")[-1][:12]  # Short container ID
                            break
                except Exception as e:
                    self.logger.debug("Could not read container ID", error=str(e))

            return {
                "running_in_docker": is_docker,
                "container_id": container_id,
                "deployment_mode": "Docker" if is_docker else "Native",
            }

        except Exception as e:
            self.logger.error("Failed to get Docker status", error=str(e))
            return {
                "running_in_docker": False,
                "error": str(e),
            }

    async def get_system_info(self) -> dict[str, Any]:
        """
        Get general system information.

        Returns:
            Dictionary with system information.
        """
        try:
            # System information
            boot_time = psutil.boot_time()
            system_uptime = time.time() - boot_time

            # CPU information
            cpu_count = psutil.cpu_count(logical=True)
            cpu_count_physical = psutil.cpu_count(logical=False)

            # Memory information
            memory = psutil.virtual_memory()

            return {
                "system_uptime_seconds": system_uptime,
                "cpu_count_logical": cpu_count,
                "cpu_count_physical": cpu_count_physical,
                "memory_total_gb": memory.total / (1024 * 1024 * 1024),
                "python_version": f"{psutil.PROCFS_PATH if hasattr(psutil, 'PROCFS_PATH') else 'N/A'}",
                "psutil_version": (
                    psutil.version_info if hasattr(psutil, "version_info") else "Unknown"
                ),
            }

        except Exception as e:
            self.logger.error("Failed to get system info", error=str(e))
            return {"error": str(e)}
