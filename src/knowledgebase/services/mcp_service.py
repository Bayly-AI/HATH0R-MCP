"""
MCP (Model Context Protocol) integration service.

Manages MCP server status, tool registration, agent activity tracking,
and usage analytics for the KnowledgeBase system.
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from knowledgebase.core.config import Settings
from knowledgebase.core.mcp_tools import get_default_mcp_tool_specs
from knowledgebase.core.models import MCPActivity, MCPServerStatus, MCPTool
from knowledgebase.services.base import BaseService


class MCPService(BaseService):
    """
    Service for managing MCP server integration and monitoring.

    Tracks tool usage, agent activity, and provides analytics
    for the Model Context Protocol integration.
    """

    def __init__(self, config: Settings) -> None:
        """
        Initialize the MCP service.

        Args:
            config: Application configuration settings.
        """
        super().__init__(config)
        self._start_time = time.time()
        self._tools: dict[str, MCPTool] = {}
        self._recent_activity: deque[MCPActivity] = deque(maxlen=100)
        self._request_counts: dict[str, int] = defaultdict(int)
        self._hourly_requests: deque[tuple[float, int]] = deque(maxlen=60)  # 60 minutes
        self._active_agents: set[str] = set()
        self._tool_call_success: dict[str, list[bool]] = defaultdict(list)

    async def _initialize_impl(self) -> None:
        """Initialize MCP service with default tools."""
        for tool_spec in get_default_mcp_tool_specs():
            await self.register_tool(name=tool_spec.name, description=tool_spec.description)

        # Initialize request tracking
        self._start_hourly_tracking()

        self.logger.info("MCP service initialized successfully", registered_tools=len(self._tools))

    async def _custom_health_check(self) -> dict[str, Any]:
        """Custom health check for MCP service."""
        return {
            "registered_tools": len(self._tools),
            "active_agents": len(self._active_agents),
            "recent_activity_count": len(self._recent_activity),
            "uptime_seconds": self._get_uptime_seconds(),
        }

    def _get_uptime_seconds(self) -> float:
        """Get service uptime in seconds."""
        return time.time() - self._start_time

    def _start_hourly_tracking(self) -> None:
        """Initialize hourly request tracking."""
        current_time = time.time()
        self._hourly_requests.append((current_time, 0))

    async def register_tool(self, name: str, description: str = "") -> MCPTool:
        """
        Register a new MCP tool.

        Args:
            name: Tool name.
            description: Tool description.

        Returns:
            MCPTool object representing the registered tool.
        """
        tool = MCPTool(
            name=name,
            description=description,
            last_used=None,
            total_calls=0,
            status="active",
            success_rate=100.0,
        )

        self._tools[name] = tool
        self.logger.info("Tool registered", tool_name=name)

        return tool

    async def record_tool_call(
        self,
        agent: str,
        tool_name: str,
        query: str,
        success: bool = True,
        response_time_ms: float = 0.0,
    ) -> None:
        """
        Record a tool call from an agent.

        Args:
            agent: Agent identifier.
            tool_name: Name of the tool called.
            query: Query or parameters passed.
            success: Whether the call was successful.
            response_time_ms: Response time in milliseconds.
        """
        current_time = datetime.now(timezone.utc)

        # Update tool statistics
        if tool_name in self._tools:
            tool = self._tools[tool_name]
            tool.last_used = current_time
            tool.total_calls += 1

            # Track success rate
            self._tool_call_success[tool_name].append(success)
            if len(self._tool_call_success[tool_name]) > 100:
                self._tool_call_success[tool_name].pop(0)

            success_calls = sum(self._tool_call_success[tool_name])
            total_calls = len(self._tool_call_success[tool_name])
            tool.success_rate = (success_calls / total_calls) * 100 if total_calls > 0 else 100.0

        # Record activity
        activity = MCPActivity(
            agent=agent,
            action=tool_name,
            query=query,
            timestamp=current_time,
            success=success,
            response_time_ms=response_time_ms,
        )

        self._recent_activity.append(activity)

        # Track active agents
        self._active_agents.add(agent)

        # Update request counts
        self._request_counts[tool_name] += 1
        self._update_hourly_requests()

        self.logger.debug(
            "Tool call recorded",
            agent=agent,
            tool=tool_name,
            success=success,
            response_time=response_time_ms,
        )

    def _update_hourly_requests(self) -> None:
        """Update hourly request tracking."""
        current_time = time.time()
        current_hour = int(current_time // 3600)

        # Remove old entries (older than 1 hour)
        while self._hourly_requests and (current_time - self._hourly_requests[0][0]) > 3600:
            self._hourly_requests.popleft()

        # Add or update current hour count
        if self._hourly_requests and int(self._hourly_requests[-1][0] // 3600) == current_hour:
            # Update existing hour entry
            _, old_count = self._hourly_requests.pop()
            self._hourly_requests.append((current_time, old_count + 1))
        else:
            # Add new hour entry
            self._hourly_requests.append((current_time, 1))

    async def get_server_status(self) -> MCPServerStatus:
        """
        Get current MCP server status and statistics.

        Returns:
            MCPServerStatus object with current status information.
        """
        self._ensure_initialized()

        # Calculate requests per hour
        current_time = time.time()
        recent_requests = sum(
            count
            for timestamp, count in self._hourly_requests
            if (current_time - timestamp) <= 3600
        )

        # Calculate overall success rate
        all_successes = []
        for successes in self._tool_call_success.values():
            all_successes.extend(successes)

        overall_success_rate = (
            (sum(all_successes) / len(all_successes)) * 100 if all_successes else 100.0
        )

        # Get tool list with current statistics
        tools = list(self._tools.values())

        # Get recent activity (last 50 items)
        recent_activity = list(self._recent_activity)[-50:]

        return MCPServerStatus(
            status="active" if tools else "inactive",
            active_agents=len(self._active_agents),
            requests_per_hour=recent_requests,
            success_rate=overall_success_rate,
            tools=tools,
            recent_activity=recent_activity,
            uptime_seconds=self._get_uptime_seconds(),
            last_health_check=datetime.now(timezone.utc),
        )

    async def get_tool_analytics(self) -> dict[str, Any]:
        """
        Get detailed analytics for MCP tools.

        Returns:
            Dictionary with tool usage analytics.
        """
        self._ensure_initialized()

        analytics: dict[str, Any] = {
            "total_tools": len(self._tools),
            "total_calls": sum(tool.total_calls for tool in self._tools.values()),
            "active_tools": len([tool for tool in self._tools.values() if tool.status == "active"]),
            "tool_usage_ranking": [],
            "most_used_tools": [],
            "agent_activity": {},
        }

        # Tool usage ranking
        sorted_tools = sorted(self._tools.values(), key=lambda t: t.total_calls, reverse=True)

        analytics["tool_usage_ranking"] = [
            {
                "name": tool.name,
                "calls": tool.total_calls,
                "success_rate": tool.success_rate,
                "last_used": tool.last_used.isoformat() if tool.last_used else None,
            }
            for tool in sorted_tools
        ]

        # Most used tools (top 5)
        analytics["most_used_tools"] = analytics["tool_usage_ranking"][:5]

        # Agent activity summary
        agent_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "tools_used": set()}
        )

        for activity in self._recent_activity:
            agent_stats[activity.agent]["calls"] += 1
            agent_stats[activity.agent]["tools_used"].add(activity.action)

        analytics["agent_activity"] = {
            agent: {
                "total_calls": stats["calls"],
                "unique_tools": len(stats["tools_used"]),
                "tools": list(stats["tools_used"]),
            }
            for agent, stats in agent_stats.items()
        }

        return analytics

    async def get_agent_list(self) -> list[dict[str, Any]]:
        """
        Get list of active agents with their activity summary.

        Returns:
            List of agent information dictionaries.
        """
        self._ensure_initialized()

        agent_info = []

        # Collect agent statistics from recent activity
        agent_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "calls": 0,
                "last_activity": None,
                "tools_used": set(),
                "success_rate": [],
            }
        )

        for activity in self._recent_activity:
            stats = agent_stats[activity.agent]
            stats["calls"] += 1
            stats["tools_used"].add(activity.action)
            stats["success_rate"].append(activity.success)

            if stats["last_activity"] is None or activity.timestamp > stats["last_activity"]:
                stats["last_activity"] = activity.timestamp

        # Convert to list format
        for agent, stats in agent_stats.items():
            success_rate = (
                (sum(stats["success_rate"]) / len(stats["success_rate"])) * 100
                if stats["success_rate"]
                else 100.0
            )

            agent_info.append(
                {
                    "name": agent,
                    "total_calls": stats["calls"],
                    "unique_tools_used": len(stats["tools_used"]),
                    "success_rate": success_rate,
                    "last_activity": (
                        stats["last_activity"].isoformat() if stats["last_activity"] else None
                    ),
                    "status": "active" if agent in self._active_agents else "inactive",
                }
            )

        # Sort by activity (most recent first)
        agent_info.sort(key=lambda x: x["last_activity"] or "1970-01-01T00:00:00Z", reverse=True)

        return agent_info

    async def cleanup_old_activity(self, hours: int = 24) -> int:
        """
        Clean up old activity records.

        Args:
            hours: Hours to keep activity records (default: 24).

        Returns:
            Number of records removed.
        """
        cutoff_time = datetime.now(timezone.utc).timestamp() - (hours * 3600)

        original_count = len(self._recent_activity)

        # Remove old activities
        while (
            self._recent_activity and self._recent_activity[0].timestamp.timestamp() < cutoff_time
        ):
            self._recent_activity.popleft()

        removed_count = original_count - len(self._recent_activity)

        if removed_count > 0:
            self.logger.info(
                "Cleaned up old activity records",
                removed=removed_count,
                remaining=len(self._recent_activity),
            )

        return removed_count

    async def reset_tool_stats(self, tool_name: str) -> bool:
        """
        Reset statistics for a specific tool.

        Args:
            tool_name: Name of the tool to reset.

        Returns:
            True if tool was found and reset, False otherwise.
        """
        if tool_name not in self._tools:
            return False

        tool = self._tools[tool_name]
        tool.total_calls = 0
        tool.last_used = None
        tool.success_rate = 100.0

        # Clear success rate tracking
        self._tool_call_success[tool_name].clear()

        self.logger.info("Tool statistics reset", tool_name=tool_name)
        return True
