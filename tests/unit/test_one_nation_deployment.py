"""Protect shared-suite operations and isolation from the source deployment."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_joins_atc_group_without_redefining_shared_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert compose["name"] == "1-nation"
    assert set(compose["services"]) == {"1n-mcp"}
    service = compose["services"]["1n-mcp"]
    assert service["container_name"] == "1NMCP"
    assert service["image"] == "1-nation/mcp:local"
    assert service["labels"] == {
        "com.1nation.org": "bayly-ai",
        "com.1nation.project": "1n-suite",
        "com.1nation.component": "mcp",
        "com.1nation.container": "1NMCP",
    }
    assert compose["networks"]["1-nation-net"]["external"] is True
    assert "1-nation-net" in service["networks"]
    assert all("bai" not in mount.lower() for mount in service["volumes"])
    assert service["ports"][0].startswith("127.0.0.1:")


def test_seed_sources_exist_and_remote_sync_is_disabled():
    config = json.loads((ROOT / "cfg/knowledgebase.json").read_text())
    for index in config["indices"]:
        source = (ROOT / index["sync_source"]).resolve()
        assert source.is_relative_to(ROOT / "knowledgebase")
        assert source.is_dir()
    assert json.loads((ROOT / "cfg/sync.json").read_text()) == {"targets": {}}
    runtime = json.loads((ROOT / "cfg/cfg.json").read_text())["runtime"]
    assert runtime["modes"]["docker"]["service"] == "1n-mcp"


def test_makefile_never_tears_down_shared_project():
    makefile = (ROOT / "Makefile").read_text()
    assert "--remove-orphans" not in makefile
    assert " down" not in makefile
    assert "stop 1n-mcp" in makefile
