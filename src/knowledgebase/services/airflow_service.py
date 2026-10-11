"""Apache Airflow integration service for HATH0R-MCP."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class AirflowService:
    """Service to communicate with Apache Airflow REST API (v1 / v2)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("AIRFLOW_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")
        self.username = username or os.getenv("AIRFLOW_USERNAME", "admin")
        self.password = password or os.getenv("AIRFLOW_PASSWORD", "admin")
        self.token = token or os.getenv("AIRFLOW_API_TOKEN")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.username and self.password:
            auth_str = f"{self.username}:{self.password}"
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            headers["Authorization"] = f"Basic {encoded}"
        return headers

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        data = json.dumps(payload).encode("utf-8") if payload is not None else None

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                return {"status_code": status_code, "data": parsed, "success": True}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            return {
                "status_code": e.code,
                "error": f"HTTP {e.code}: {e.reason}",
                "detail": err_body,
                "success": False,
            }
        except urllib.error.URLError as e:
            return {
                "status_code": 503,
                "error": f"Airflow unreachable at {self.base_url}: {e.reason}",
                "success": False,
            }
        except Exception as e:
            return {
                "status_code": 500,
                "error": f"Internal error querying Airflow: {str(e)}",
                "success": False,
            }

    def list_dags(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """List configured DAGs in the Airflow environment."""
        endpoint = f"dags?limit={limit}&offset={offset}"
        return self._request(endpoint, method="GET")

    def trigger_dag(self, dag_id: str, conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Trigger execution of an Airflow DAG."""
        endpoint = f"dags/{dag_id}/dagRuns"
        payload = {"conf": conf or {}}
        return self._request(endpoint, method="POST", payload=payload)

    def get_dag_run(self, dag_id: str, dag_run_id: str) -> Dict[str, Any]:
        """Inspect status of a specific DAG run."""
        endpoint = f"dags/{dag_id}/dagRuns/{dag_run_id}"
        return self._request(endpoint, method="GET")


_default_airflow_service: Optional[AirflowService] = None


def get_airflow_service() -> AirflowService:
    """Return singleton AirflowService instance."""
    global _default_airflow_service
    if _default_airflow_service is None:
        _default_airflow_service = AirflowService()
    return _default_airflow_service
