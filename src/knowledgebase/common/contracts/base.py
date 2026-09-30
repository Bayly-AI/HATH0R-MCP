"""
Base contracts and data types for service architecture.

Defines common interfaces, exceptions, and data structures used across services.
"""

from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ServiceError(Exception):
    """Base exception for service-related errors."""

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ServiceUnavailableError(ServiceError):
    """Raised when a service is unavailable."""

    def __init__(self, service_name: str, message: str | None = None):
        super().__init__(
            message or f"Service {service_name} is unavailable", error_code="SERVICE_UNAVAILABLE"
        )
        self.service_name = service_name


@dataclass
class HealthStatus:
    """Health status information for a service."""

    service_name: str
    status: str  # "healthy", "unhealthy", "degraded"
    version: str
    checks: dict[str, Any] | None = None
    dependencies: dict[str, Any] | None = None
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.checks is None:
            self.checks = {}
        if self.dependencies is None:
            self.dependencies = {}


@dataclass
class ServiceMetadata:
    """Service metadata for discovery and documentation."""

    name: str
    version: str
    description: str
    api_version: str
    endpoints: list[str] | None = None
    dependencies: list[str] | None = None
    tags: list[str] | None = None

    def __post_init__(self) -> None:
        if self.endpoints is None:
            self.endpoints = []
        if self.dependencies is None:
            self.dependencies = []
        if self.tags is None:
            self.tags = []


class ServiceContract(ABC):
    """Abstract base contract for services."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize service resources."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup service resources."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Return service health status."""
        pass

    @abstractmethod
    def get_metadata(self) -> ServiceMetadata:
        """Return service metadata for discovery."""
        pass
