"""Verify a running service with the official MCP client and real tool calls."""

import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def verify(base_url: str) -> dict:
    headers = {}
    token = os.getenv("HATH0R_MCP_TOKEN") or os.getenv("N1_MCP_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(headers=headers, timeout=15) as http:
        for endpoint in ("health", "ready", "version"):
            response = await http.get(f"{base_url}/{endpoint}")
            response.raise_for_status()
        async with streamable_http_client(f"{base_url}/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "HATH0R-MCP"
                catalog = await session.list_tools()
                assert {tool.name for tool in catalog.tools} == {
                    "suite_info",
                    "kb_search",
                    "kb_get_document",
                    "voice_speak",
                    "voice_listen",
                    "voice_dispatch_action",
                }
                info = await session.call_tool("suite_info", {})
                assert not info.isError
                data = json.loads(info.content[0].text)
                assert data.get("service") == "hath0r-mcp"
                assert data.get("project") == "hath0r"
                doc = await session.call_tool(
                    "kb_get_document", {"document_id": data["documents"][0]["id"]}
                )
                assert not doc.isError
                # Prefer Hath0r terms; fall back to generic corpus word
                search = await session.call_tool("kb_search", {"query": "hath0r suite knowledge"})
                assert not search.isError
                results = json.loads(search.content[0].text)["results"]
                if not results:
                    search = await session.call_tool("kb_search", {"query": "suite"})
                    assert not search.isError
                    results = json.loads(search.content[0].text)["results"]
                assert results
    return {"api": "ok", "mcp": "ok", "tools": len(catalog.tools)}


def smoke(base_url: str) -> None:
    print(json.dumps(asyncio.run(verify(base_url.rstrip("/"))), indent=2))


if __name__ == "__main__":
    default_base = "http://127.0.0.1:8083"
    smoke(os.getenv("HATH0R_MCP_BASE_URL") or os.getenv("N1_MCP_BASE_URL", default_base))
