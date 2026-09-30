# Hath0r MCP — standalone member of OpenSource Docker group (hath0r)
SHELL := /bin/sh
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMPOSE := docker compose -p hath0r -f $(ROOT)/docker-compose.yml
NETWORK_NAME ?= hath0r-net
SERVICE ?= hath0r-mcp
HATH0R_MCP_HOST_PORT ?= 38083
PYTHON ?= python3

.PHONY: help bootstrap install test \
	docker-config docker-build docker-up docker-stop docker-down docker-status docker-logs docker-ps \
	smoke smoke-local serve network-ensure

help:
	@echo "Hath0r MCP (standalone member on $(NETWORK_NAME), project hath0r)"
	@echo "  make bootstrap       - Hath0r fileset bootstrap validation"
	@echo "  make install         - Create venv and install deps"
	@echo "  make test            - Pytest with coverage mode"
	@echo "  make serve           - Local FastMCP on :8083"
	@echo "  make smoke-local     - MCP smoke against local process"
	@echo "  make docker-config   - Validate compose"
	@echo "  make docker-build    - Build $(SERVICE) image (hath0r/mcp:local)"
	@echo "  make docker-up       - Start $(SERVICE) on hath0r-net (wait healthy)"
	@echo "  make docker-stop     - Stop $(SERVICE) only (do not tear down ATC shared infra)"
	@echo "  make docker-down     - Remove $(SERVICE) container only"
	@echo "  make docker-status | docker-logs | docker-ps"
	@echo "  make smoke           - In-container MCP smoke"
	@echo "  Host: http://localhost:$(HATH0R_MCP_HOST_PORT)/  (health/ready/mcp)"

bootstrap:
	./bin/hath0r-bootstrap.sh

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.txt -e .

test:
	KB_TEST_MODE=1 $(PYTHON) -m pytest -v --tb=short

network-ensure:
	@docker network inspect $(NETWORK_NAME) >/dev/null 2>&1 || \
		docker network create \
			--label com.hath0r.org=bayly-ai \
			--label com.hath0r.project=hath0r-opensource \
			--label com.hath0r.component=network \
			$(NETWORK_NAME)
	@echo "✓ network $(NETWORK_NAME)"

docker-config:
	@$(COMPOSE) config --quiet
	@echo "✓ compose config ok (project hath0r, service $(SERVICE))"

docker-build:
	@$(COMPOSE) build $(SERVICE)
	@echo "✓ image hath0r/mcp:local"

docker-up: network-ensure
	@HATH0R_MCP_HOST_PORT=$(HATH0R_MCP_HOST_PORT) $(COMPOSE) up -d --build --wait $(SERVICE)
	@echo "✓ $(SERVICE) up on :$(HATH0R_MCP_HOST_PORT) (group hath0r / $(NETWORK_NAME))"

# Scoped stop — never remove ATC shared redis/nginx/postgres
docker-stop:
	@$(COMPOSE) stop $(SERVICE)
	@echo "✓ $(SERVICE) stopped (shared hath0r infra untouched)"

docker-down:
	@$(COMPOSE) rm -f -s $(SERVICE) 2>/dev/null || $(COMPOSE) stop $(SERVICE)
	@echo "✓ $(SERVICE) removed/stopped (shared hath0r infra untouched)"

docker-status:
	@$(COMPOSE) ps $(SERVICE)
	@docker inspect -f 'health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}} status={{.State.Status}}' $(SERVICE) 2>/dev/null || echo "$(SERVICE) missing"

docker-ps:
	@docker ps -a --filter label=com.docker.compose.project=hath0r --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

docker-logs:
	@$(COMPOSE) logs --tail=100 -f $(SERVICE)

smoke:
	@$(COMPOSE) exec -T $(SERVICE) python /app/src/knowledgebase/cli/smoke.py

smoke-local:
	@$(PYTHON) -m knowledgebase.cli.smoke

serve:
	@$(PYTHON) -m uvicorn knowledgebase.server:app --host 0.0.0.0 --port 8083
