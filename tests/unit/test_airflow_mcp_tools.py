"""Unit tests for Apache Airflow MCP integration in HATH0R-MCP."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from knowledgebase.core.mcp_tools import get_default_mcp_tool_specs
from knowledgebase.services.airflow_service import AirflowService
from knowledgebase.api.main import _execute_mcp_tool


class TestAirflowMCPTools:
    """Test suite for Airflow MCP tools and service integration."""

    def test_airflow_tool_specs_registered(self):
        specs = {s.name: s for s in get_default_mcp_tool_specs()}
        assert "airflow_list_dags" in specs
        assert "airflow_trigger_dag" in specs
        assert "airflow_get_dag_run" in specs

        assert "dag_id" in specs["airflow_trigger_dag"].input_schema["required"]
        assert "dag_run_id" in specs["airflow_get_dag_run"].input_schema["required"]

    def test_airflow_service_auth_headers_token(self):
        svc = AirflowService(base_url="http://airflow:8080", token="secret-token-123")
        headers = svc._get_headers()
        assert headers["Authorization"] == "Bearer secret-token-123"

    def test_airflow_service_auth_headers_basic(self):
        svc = AirflowService(base_url="http://airflow:8080", username="user", password="pwd", token=None)
        headers = svc._get_headers()
        assert headers["Authorization"].startswith("Basic ")

    @patch("urllib.request.urlopen")
    def test_airflow_service_list_dags(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({"dags": [{"dag_id": "test_dag_1"}]}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        svc = AirflowService(base_url="http://airflow:8080")
        res = svc.list_dags(limit=10)
        assert res["success"] is True
        assert res["data"] == {"dags": [{"dag_id": "test_dag_1"}]}

    @patch("urllib.request.urlopen")
    def test_airflow_service_trigger_dag(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 201
        mock_resp.read.return_value = json.dumps({"dag_run_id": "manual__2026-10-11", "state": "queued"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        svc = AirflowService(base_url="http://airflow:8080")
        res = svc.trigger_dag("test_dag", conf={"param": "value"})
        assert res["success"] is True
        assert res["data"]["state"] == "queued"

    @pytest.mark.asyncio
    @patch("knowledgebase.services.airflow_service.AirflowService.list_dags")
    async def test_execute_mcp_tool_airflow_list_dags(self, mock_list):
        mock_list.return_value = {"success": True, "data": {"dags": []}}
        result = await _execute_mcp_tool("airflow_list_dags", {"limit": 5})
        assert "content" in result
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["success"] is True

    @pytest.mark.asyncio
    @patch("knowledgebase.services.airflow_service.AirflowService.trigger_dag")
    async def test_execute_mcp_tool_airflow_trigger_dag(self, mock_trigger):
        mock_trigger.return_value = {"success": True, "data": {"state": "queued"}}
        result = await _execute_mcp_tool("airflow_trigger_dag", {"dag_id": "elt_pipeline"})
        assert "content" in result
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_airflow_missing_param_fails(self):
        result = await _execute_mcp_tool("airflow_trigger_dag", {})
        assert result.get("isError") is True
        assert "Missing required argument" in result["content"][0]["text"]
