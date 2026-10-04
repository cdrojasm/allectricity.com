COMPOSE = docker compose --env-file .env -f deploy/local/docker/docker-compose.yml

.DEFAULT_GOAL := help

.PHONY: help
help:
	@printf '%s\n' \
	  'Available commands:' \
	  '  frontend-build Build frontend static files' \
	  '  potential-engine Build the C++ grounding-potential engine' \
	  '  frontend-up    Build static files and start Nginx' \
	  '  frontend-down  Stop the Nginx container' \
	  '  local-build    Build local Docker services' \
	  '  local-up       Build and start local Docker services' \
	  '  local-down     Stop and remove local Docker services' \
	  '  test           Build and run backend tests' \
	  '  lint           Run backend lint checks' \
	  '  local-config  Configure local environment' \
	  '  migrate        Run database migrations' \
	  '  create-admin   Create the local admin user' \
	  '  smoke-auth     Run the authentication smoke check' \
	  '  sync-prompts   Publish new Langfuse prompt versions with the staging label'

.PHONY: local-up local-down local-build test lint

.PHONY: frontend-build frontend-up frontend-down potential-engine
potential-engine:
	mkdir -p services/potential_engine/build
	g++ -std=c++17 -O3 -Wall -Wextra -Wpedantic services/potential_engine/src/main.cpp -o services/potential_engine/build/spat-potential-engine

frontend-build:
	npm --prefix app run build

frontend-up: frontend-build
	$(COMPOSE) up -d nginx

frontend-down:
	$(COMPOSE) stop nginx

local-build:
	$(COMPOSE) build

local-up: frontend-build
	$(COMPOSE) up --build -d

local-down:
	$(COMPOSE) down

test:
	$(COMPOSE) --profile test build tests
	$(COMPOSE) --profile test run --rm tests

lint:
	$(COMPOSE) --profile test build tests
	$(COMPOSE) --profile test run --rm --no-deps tests ruff check --no-cache src tests --select E9,F63,F7,F82

.PHONY: local-config migrate create-admin sync-prompts
local-config:
	docker run --rm --name grounding-design-ai-config -v "$(CURDIR):/workspace" -w /workspace python:3.12-alpine python scripts/configure_local.py

migrate:
	$(COMPOSE) run --rm migrate

create-admin:
	$(COMPOSE) exec api python -m src.infrastructure.entrypoint.bootstrap_admin

sync-prompts:
	$(COMPOSE) run --rm --no-deps worker python scripts/sync_langfuse_prompts.py

.PHONY: smoke-auth
smoke-auth:
	$(COMPOSE) exec -T api python -m scripts.smoke_auth
