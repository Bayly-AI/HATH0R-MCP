"""
Core data models for KnowledgeBase Engine.

Defines the primary data structures used throughout the application.
"""

from __future__ import annotations


from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentMetadata(BaseModel):
    """
    Metadata associated with a document.

    Attributes:
        path: File path or URL of the source document.
        title: Document title.
        source_type: Type of source (e.g., 'file', 'confluence', 'code').
        repository: Repository name for code documents.
        space: Confluence space key.
        tags: List of tags for categorization.
        language: Programming language for code documents.
        author: Document author.
        created_at: Document creation timestamp.
        updated_at: Last update timestamp.
        extra: Additional metadata fields.
    """

    path: str | None = None
    title: str | None = None
    source_type: str | None = None
    repository: str | None = None
    space: str | None = None
    tags: list[str] = Field(default_factory=list)
    language: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    # Pydantic v2 configuration uses ``model_config`` instead of the
    # v1-style ``Config`` inner class. Allowing extra fields keeps the
    # metadata model forwards-compatible with new attributes.
    model_config = ConfigDict(extra="allow")


class Document(BaseModel):
    """
    A document to be indexed and searched.

    Attributes:
        id: Unique document identifier.
        content: Document text content.
        embedding: Vector embedding of the content.
        metadata: Document metadata.
        index_name: Name of the index this document belongs to.
        chunk_index: Index of this chunk within the source document.
        total_chunks: Total number of chunks from the source document.
    """

    id: str
    content: str
    embedding: list[float] | None = None
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    index_name: str = "knowledgebase"
    chunk_index: int = 0
    total_chunks: int = 1

    @property
    def has_embedding(self) -> bool:
        """Check if the document has an embedding."""
        return self.embedding is not None and len(self.embedding) > 0


class SearchResult(BaseModel):
    """
    A search result containing a matched document and relevance score.

    Attributes:
        document: The matched document.
        score: Relevance score (0.0 to 1.0, higher is more relevant).
        vector_score: Score from vector similarity search.
        bm25_score: Score from BM25 text search.
        highlights: Text snippets with matching terms highlighted.
    """

    document: Document
    score: float = Field(ge=0.0, le=1.0)
    vector_score: float | None = None
    bm25_score: float | None = None
    highlights: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """
    A search query with filters and options.

    Attributes:
        query: Search query text.
        index_name: Name of the index to search (None for all indices).
        limit: Maximum number of results to return.
        min_score: Minimum relevance score threshold.
        filters: Metadata filters to apply.
        include_embeddings: Whether to include embeddings in results.
        hybrid_alpha: Weight for vector vs BM25 (1.0 = pure vector).
    """

    query: str
    index_name: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    filters: dict[str, Any] = Field(default_factory=dict)
    include_embeddings: bool = False
    hybrid_alpha: float = Field(default=0.7, ge=0.0, le=1.0)


class IndexInfo(BaseModel):
    """
    Information about a search index.

    Attributes:
        name: Index name.
        description: Human-readable description.
        document_count: Number of documents in the index.
        sync_source: Path to the sync source directory.
        last_sync: Timestamp of the last sync operation.
        metadata_schema: Schema for document metadata in this index.
    """

    name: str
    description: str = ""
    document_count: int = 0
    sync_source: str | None = None
    last_sync: datetime | None = None
    metadata_schema: dict[str, str] = Field(default_factory=dict)


class SyncStatus(BaseModel):
    """
    Status of a sync operation.

    Attributes:
        index_name: Name of the index being synced.
        status: Current status ('pending', 'running', 'completed', 'failed').
        documents_processed: Number of documents processed.
        documents_added: Number of new documents added.
        documents_updated: Number of documents updated.
        documents_deleted: Number of documents deleted.
        errors: List of error messages.
        started_at: Timestamp when sync started.
        completed_at: Timestamp when sync completed.
    """

    index_name: str
    status: str = "pending"
    documents_processed: int = 0
    documents_added: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SystemStats(BaseModel):
    """
    System-level statistics and metrics.

    Attributes:
        total_documents: Total number of documents across all indices.
        total_indices: Total number of indices.
        total_searches: Total number of searches performed.
        uptime_seconds: System uptime in seconds.
        memory_usage_mb: Current memory usage in MB.
        storage_usage_gb: Current storage usage in GB.
        active_connections: Number of active client connections.
    """

    total_documents: int
    total_indices: int
    total_searches: int
    uptime_seconds: float
    memory_usage_mb: float
    storage_usage_gb: float = 0.0
    active_connections: int = 0


class MemoryUsage(BaseModel):
    """
    Memory usage statistics.

    Attributes:
        used_gb: Memory currently in use (GB).
        total_gb: Total system memory (GB).
        percentage: Memory usage percentage (0-100).
    """

    used_gb: float
    total_gb: float
    percentage: float = Field(ge=0.0, le=100.0)


class StorageUsage(BaseModel):
    """
    Storage usage statistics.

    Attributes:
        used_gb: Storage currently in use (GB).
        total_gb: Total storage capacity (GB).
        percentage: Storage usage percentage (0-100).
    """

    used_gb: float
    total_gb: float
    percentage: float = Field(ge=0.0, le=100.0)


class PerformanceMetrics(BaseModel):
    """
    System performance metrics.

    Attributes:
        cpu_usage: CPU usage percentage (0-100).
        memory_usage: Memory usage details.
        storage_usage: Storage usage details.
        network_throughput: Network throughput in MB/s.
        disk_io_read_mb_s: Disk read speed in MB/s.
        disk_io_write_mb_s: Disk write speed in MB/s.
        timestamp: Timestamp when metrics were collected.
    """

    cpu_usage: float = Field(ge=0.0, le=100.0)
    memory_usage: MemoryUsage
    storage_usage: StorageUsage
    network_throughput: float = 0.0
    disk_io_read_mb_s: float = 0.0
    disk_io_write_mb_s: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class MCPTool(BaseModel):
    """
    MCP tool information.

    Attributes:
        name: Tool name.
        description: Tool description.
        last_used: Timestamp of last usage.
        total_calls: Total number of calls made to this tool.
        status: Tool status ('active', 'inactive', 'error').
        success_rate: Success rate percentage (0-100).
    """

    name: str
    description: str = ""
    last_used: datetime | None = None
    total_calls: int = 0
    status: str = "active"
    success_rate: float = Field(default=100.0, ge=0.0, le=100.0)


class MCPActivity(BaseModel):
    """
    MCP agent activity record.

    Attributes:
        agent: Agent identifier.
        action: Action performed (tool name).
        query: Query or parameters passed.
        timestamp: When the action occurred.
        success: Whether the action was successful.
        response_time_ms: Response time in milliseconds.
    """

    agent: str
    action: str
    query: str
    timestamp: datetime
    success: bool = True
    response_time_ms: float = 0.0


class MCPServerStatus(BaseModel):
    """
    MCP server status and statistics.

    Attributes:
        status: Server status ('active', 'inactive', 'degraded').
        active_agents: Number of currently connected agents.
        requests_per_hour: Request rate per hour.
        success_rate: Overall success rate percentage (0-100).
        tools: List of available tools.
        recent_activity: Recent agent activity records.
        uptime_seconds: Server uptime in seconds.
        last_health_check: Timestamp of last health check.
    """

    status: str = "active"
    active_agents: int = 0
    requests_per_hour: int = 0
    success_rate: float = Field(default=100.0, ge=0.0, le=100.0)
    tools: list[MCPTool] = Field(default_factory=list)
    recent_activity: list[MCPActivity] = Field(default_factory=list)
    uptime_seconds: float = 0.0
    last_health_check: datetime = Field(default_factory=lambda: datetime.now())


class ServiceStatus(BaseModel):
    """
    Individual service health status.

    Attributes:
        name: Service name.
        status: Health status ('healthy', 'degraded', 'unhealthy').
        url: Service URL or endpoint.
        port: Service port.
        uptime: Uptime percentage.
        last_check: Last health check timestamp.
        response_time_ms: Average response time in milliseconds.
    """

    name: str
    status: str = "healthy"
    url: str = ""
    port: int = 0
    uptime: str = "0.0%"
    last_check: datetime = Field(default_factory=lambda: datetime.now())
    response_time_ms: float = 0.0


class ToolTestResult(BaseModel):
    """
    Result of testing an MCP tool.
    """

    name: str
    status: str = "pass"
    duration_ms: float
    error_message: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class EndpointTestResult(BaseModel):
    """
    Result of testing an API endpoint.
    """

    path: str
    method: str
    status_code: int | None = None
    duration_ms: float
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class SyncStatusInfo(BaseModel):
    """
    Information about the latest sync operation.
    """

    last_sync_time: datetime | None = None
    sync_duration_seconds: float = 0.0
    indices_synced: int = 0
    documents_synced: int = 0
    sync_errors: list[str] = Field(default_factory=list)


class AggregateStats(BaseModel):
    """
    Aggregate system statistics for full status reporting.
    """

    total_documents: int = 0
    total_indices: int = 0
    total_runbooks: int = 0
    total_rules: int = 0
    uptime_seconds: float = 0.0
    uptime_formatted: str = ""
    last_interaction_ago: str = "never"
    memory_usage_mb: float = 0.0
    storage_usage_gb: float = 0.0
    search_count: int = 0


class DiagnosticIssue(BaseModel):
    """
    A diagnostic issue identified during comprehensive status checks.
    """

    severity: str
    component: str
    message: str
    recommendation: str | None = None


class DiagnosticReport(BaseModel):
    """
    Summary report for full status diagnostics.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    duration_ms: float = 0.0
    tools_passed: int = 0
    tools_failed: int = 0
    endpoints_passed: int = 0
    endpoints_failed: int = 0
    issues: list[DiagnosticIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class FullStatusResponse(BaseModel):
    """
    Complete status response payload.
    """

    overall_status: str = "healthy"
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    tools: list[ToolTestResult] = Field(default_factory=list)
    endpoints: list[EndpointTestResult] = Field(default_factory=list)
    sync: SyncStatusInfo = Field(default_factory=SyncStatusInfo)
    stats: AggregateStats = Field(default_factory=AggregateStats)
    diagnostics: DiagnosticReport = Field(default_factory=DiagnosticReport)
