"""Protect shared-suite operations and isolation for Hath0r MCP deployment."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_joins_atc_group_without_redefining_shared_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert compose["name"] == "hath0r"
    assert set(compose["services"]) == {"hath0r-mcp"}
    service = compose["services"]["hath0r-mcp"]
    assert service["container_name"] == "hath0r-mcp"
    assert service["image"] == "hath0r/mcp:local"
    assert service["labels"] == {
        "com.hath0r.org": "bayly-ai",
        "com.hath0r.project": "hath0r-opensource",
        "com.hath0r.component": "mcp",
        "com.hath0r.container": "hath0r-mcp",
    }
    assert compose["networks"]["hath0r-net"]["external"] is True
    assert "hath0r-net" in service["networks"]
    assert all("bai" not in mount.lower() for mount in service["volumes"])
    port = service["ports"][0]
    assert "HATH0R_MCP_HOST_PORT" in port or port.startswith("127.0.0.1:")
    assert port.endswith(":8083")


def test_seed_sources_exist_and_remote_sync_is_disabled():
    config = json.loads((ROOT / "cfg/knowledgebase.json").read_text())
    for index in config["indices"]:
        source = (ROOT / index["sync_source"]).resolve()
        assert source.is_relative_to(ROOT / "knowledgebase")
        assert source.is_dir()
    assert json.loads((ROOT / "cfg/sync.json").read_text()) == {"targets": {}}
    runtime = json.loads((ROOT / "cfg/cfg.json").read_text())["runtime"]
    assert runtime["modes"]["docker"]["service"] == "hath0r-mcp"


def test_makefile_never_tears_down_shared_project():
    makefile = (ROOT / "Makefile").read_text()
    assert "--remove-orphans" not in makefile
    # Forbid full compose project teardown; scoped service stop/rm is required.
    assert "compose down" not in makefile
    assert "docker compose down" not in makefile
    assert "docker-stop" in makefile
    assert "stop $(SERVICE)" in makefile
    assert "shared hath0r infra untouched" in makefile
    assert "hath0r-net" in makefile or "NETWORK_NAME" in makefile


def test_package_and_product_identity_match_deployed_service():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    product = yaml.safe_load((ROOT / "cfg/product.yaml").read_text())
    suite = yaml.safe_load((ROOT / "cfg/suite.yaml").read_text())
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert project["name"] == product["product_id"] == suite["product_id"] == manifest["product_id_default"] == "hath0r-mcp"
    assert product["github"] == suite["github"] == "Bayly-AI/HATH0R-MCP"
    assert project["urls"]["Repository"] == "https://github.com/" + product["github"]
    assert suite["suite_hath0r"]["container_name"] == compose["services"]["hath0r-mcp"]["container_name"]
