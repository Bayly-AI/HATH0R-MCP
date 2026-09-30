"""
Base service class with common patterns for all KnowledgeBase services.

Provides standardized initialization, health checking, logging, and cleanup patterns.
"""

from __future__ import annotations


import asyncio
from abc import ABC, abstractmethod
from typing import Any

import structlog

from knowledgebase.core.config import Settings


class BaseService(ABC):
    """
    Abstract base service class with common patterns.

    All KnowledgeBase services should inherit from this class to ensure
    consistent initialization, health checking, and cleanup patterns.
    """

    def __init__(self, config: Settings) -> None:
        """
        Initialize the service with configuration.

        Args:
            config: Application configuration settings.
        """
        self.config = config
        self.logger = structlog.get_logger(self.__class__.__name__)
        self._initialized = False
        self._healthy = False
        self._initialization_error: Exception | None = None

    async def initialize(self) -> None:
        """
        Initialize the service.

        This method should be called after construction and before using the service.
        Handles initialization errors gracefully.
        """
        try:
            self.logger.info("Initializing service")
            await self._initialize_impl()
            self._initialized = True
            self._healthy = True
            self.logger.info("Service initialized successfully")
        except Exception as e:
            self._initialization_error = e
            self._healthy = False
            self.logger.error("Service initialization failed", error=str(e))
            raise

    @abstractmethod
    async def _initialize_impl(self) -> None:
        """
        Service-specific initialization logic.

        Subclasses should implement this method to perform their initialization.
        """
        pass  # pragma: no cover

    async def cleanup(self) -> None:
        """
        Clean up service resources.

        This method should be called when shutting down the service.
        """
        try:
            self.logger.info("Cleaning up service")
            await self._cleanup_impl()
            self._healthy = False
            self.logger.info("Service cleanup completed")
        except Exception as e:
            self.logger.error("Service cleanup failed", error=str(e))
            raise

    async def _cleanup_impl(self) -> None:
        """
        Service-specific cleanup logic.

        Subclasses can override this method to perform custom cleanup.
        Default implementation does nothing.
        """

    async def health_check(self) -> dict[str, Any]:
        """
        Perform health check for this service.

        Returns:
            Dictionary with health status information.
        """
        try:
            # Basic health checks
            health_data = {
                "healthy": self._healthy,
                "initialized": self._initialized,
                "service": self.__class__.__name__,
            }

            # Add initialization error if present
            if self._initialization_error:
                health_data["initialization_error"] = str(self._initialization_error)

            # Allow subclasses to add custom health checks
            custom_health = await self._custom_health_check()
            health_data.update(custom_health)

            return health_data

        except Exception as e:
            self.logger.error("Health check failed", error=str(e))
            return {
                "healthy": False,
                "service": self.__class__.__name__,
                "error": str(e),
            }

    async def _custom_health_check(self) -> dict[str, Any]:
        """
        Service-specific health check logic.

        Subclasses can override this method to add custom health checks.

        Returns:
            Dictionary with additional health status information.
        """
        return {}

    @property
    def is_healthy(self) -> bool:
        """Check if the service is healthy."""
        return self._healthy

    @property
    def is_initialized(self) -> bool:
        """Check if the service is initialized."""
        return self._initialized

    def _ensure_initialized(self) -> None:
        """
        Ensure the service is initialized before use.

        Raises:
            RuntimeError: If the service is not initialized.
        """
        if not self._initialized:
            raise RuntimeError(f"{self.__class__.__name__} is not initialized")

    async def _safe_execute(self, operation: str, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Safely execute an operation with error handling and logging.

        Args:
            operation: Name of the operation for logging.
            func: Function to execute.
            *args: Arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            Result of the function execution.

        Raises:
            Exception: Re-raises any exception after logging.
        """
        try:
            self.logger.debug("Executing operation", operation=operation)

            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            self.logger.debug("Operation completed successfully", operation=operation)
            return result
        except Exception as e:
            self.logger.error(
                "Operation failed",
                operation=operation,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise


class ServiceRegistry:
    """
    Registry for managing service instances and their lifecycle.

    Provides centralized service management with health monitoring
    and graceful shutdown capabilities.
    """

    def __init__(self) -> None:
        """Initialize the service registry."""
        self.services: dict[str, BaseService] = {}
        self.logger = structlog.get_logger(self.__class__.__name__)

    def register(self, name: str, service: BaseService) -> None:
        """
        Register a service with the registry.

        Args:
            name: Unique name for the service.
            service: Service instance to register.
        """
        self.services[name] = service
        self.logger.info("Service registered", service_name=name)

    def get(self, name: str) -> BaseService | None:
        """
        Get a service by name.

        Args:
            name: Service name.

        Returns:
            Service instance or None if not found.
        """
        return self.services.get(name)

    async def initialize_all(self) -> None:
        """Initialize all registered services."""
        self.logger.info("Initializing all services", count=len(self.services))

        for name, service in self.services.items():
            try:
                await service.initialize()
                self.logger.info("Service initialized", service_name=name)
            except Exception as e:
                self.logger.error("Failed to initialize service", service_name=name, error=str(e))
                raise

    async def cleanup_all(self) -> None:
        """Clean up all registered services."""
        self.logger.info("Cleaning up all services", count=len(self.services))

        for name, service in self.services.items():
            try:
                await service.cleanup()
                self.logger.info("Service cleaned up", service_name=name)
            except Exception as e:
                self.logger.error("Failed to cleanup service", service_name=name, error=str(e))

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """
        Perform health checks on all services.

        Returns:
            Dictionary mapping service names to their health status.
        """
        health_results = {}

        for name, service in self.services.items():
            try:
                health_results[name] = await service.health_check()
            except Exception as e:
                health_results[name] = {
                    "healthy": False,
                    "error": str(e),
                    "service": name,
                }

        return health_results

    def get_healthy_services(self) -> list[str]:
        """
        Get list of healthy service names.

        Returns:
            List of service names that are currently healthy.
        """
        return [name for name, service in self.services.items() if service.is_healthy]

    def get_unhealthy_services(self) -> list[str]:
        """
        Get list of unhealthy service names.

        Returns:
            List of service names that are currently unhealthy.
        """
        return [name for name, service in self.services.items() if not service.is_healthy]


# Global service registry instance
service_registry = ServiceRegistry()
