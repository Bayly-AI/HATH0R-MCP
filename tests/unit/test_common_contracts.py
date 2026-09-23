"""Tests for common contracts base to improve coverage."""

import pytest

from knowledgebase.common.contracts.base import (
    HealthStatus,
    ServiceContract,
    ServiceError,
    ServiceMetadata,
    ServiceUnavailableError,
)


class TestServiceError:
    """Test ServiceError exception classes."""

    def test_service_error_minimal(self) -> None:
        """Test ServiceError with minimal parameters."""
        error = ServiceError("Test error")

        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.error_code is None

    def test_service_error_with_code(self) -> None:
        """Test ServiceError with error code."""
        error = ServiceError("Test error", error_code="TEST_ERROR")

        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.error_code == "TEST_ERROR"

    def test_service_unavailable_error_minimal(self) -> None:
        """Test ServiceUnavailableError with minimal parameters."""
        error = ServiceUnavailableError("test-service")

        assert "Service test-service is unavailable" in str(error)
        assert error.service_name == "test-service"
        assert error.error_code == "SERVICE_UNAVAILABLE"

    def test_service_unavailable_error_with_message(self) -> None:
        """Test ServiceUnavailableError with custom message."""
        error = ServiceUnavailableError("test-service", "Custom message")

        assert str(error) == "Custom message"
        assert error.service_name == "test-service"
        assert error.error_code == "SERVICE_UNAVAILABLE"


class TestHealthStatus:
    """Test HealthStatus dataclass."""

    def test_health_status_minimal(self) -> None:
        """Test HealthStatus with minimal parameters."""
        status = HealthStatus(service_name="test-service", status="healthy", version="1.0.0")

        assert status.service_name == "test-service"
        assert status.status == "healthy"
        assert status.version == "1.0.0"
        assert status.checks == {}
        assert status.dependencies == {}
        assert status.timestamp is None

    def test_health_status_full(self) -> None:
        """Test HealthStatus with all parameters."""
        checks = {"database": "ok", "cache": "ok"}
        dependencies = {"external-api": "healthy"}

        status = HealthStatus(
            service_name="test-service",
            status="degraded",
            version="1.0.0",
            checks=checks,
            dependencies=dependencies,
            timestamp="2023-01-01T00:00:00Z",
        )

        assert status.service_name == "test-service"
        assert status.status == "degraded"
        assert status.version == "1.0.0"
        assert status.checks == checks
        assert status.dependencies == dependencies
        assert status.timestamp == "2023-01-01T00:00:00Z"


class TestServiceMetadata:
    """Test ServiceMetadata dataclass."""

    def test_service_metadata_minimal(self) -> None:
        """Test ServiceMetadata with minimal parameters."""
        metadata = ServiceMetadata(
            name="test-service", version="1.0.0", description="Test service", api_version="v1"
        )

        assert metadata.name == "test-service"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test service"
        assert metadata.api_version == "v1"
        assert metadata.endpoints == []
        assert metadata.dependencies == []
        assert metadata.tags == []

    def test_service_metadata_full(self) -> None:
        """Test ServiceMetadata with all parameters."""
        endpoints = ["/health", "/api/v1/status"]
        dependencies = ["database", "cache"]
        tags = ["api", "microservice"]

        metadata = ServiceMetadata(
            name="test-service",
            version="1.0.0",
            description="Test service",
            api_version="v1",
            endpoints=endpoints,
            dependencies=dependencies,
            tags=tags,
        )

        assert metadata.name == "test-service"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test service"
        assert metadata.api_version == "v1"
        assert metadata.endpoints == endpoints
        assert metadata.dependencies == dependencies
        assert metadata.tags == tags


class MockServiceContract(ServiceContract):
    """Mock implementation of ServiceContract for testing."""

    def __init__(self):
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def health_check(self) -> HealthStatus:
        return HealthStatus(service_name="mock-service", status="healthy", version="1.0.0")

    def get_metadata(self) -> ServiceMetadata:
        return ServiceMetadata(
            name="mock-service",
            version="1.0.0",
            description="Mock service for testing",
            api_version="v1",
        )


class TestServiceContract:
    """Test ServiceContract abstract base class."""

    @pytest.mark.asyncio
    async def test_service_contract_implementation(self) -> None:
        """Test that ServiceContract can be implemented."""
        service = MockServiceContract()

        # Test initialization
        assert not service.initialized
        await service.initialize()
        assert service.initialized

        # Test health check
        health = await service.health_check()
        assert health.service_name == "mock-service"
        assert health.status == "healthy"

        # Test metadata
        metadata = service.get_metadata()
        assert metadata.name == "mock-service"
        assert metadata.version == "1.0.0"

        # Test shutdown
        assert not service.shutdown_called
        await service.shutdown()
        assert service.shutdown_called
