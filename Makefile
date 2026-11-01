COMPOSE = docker compose --env-file .env -f deploy/local/docker/docker-compose.yml

.DEFAULT_GOAL := help

BENCH_OUT ?= /tmp/free-geometry-benchmark.json
free-geometry-benchmark: potential-engine
	python3 services/potential_engine/validation/free_geometry_benchmark.py --json "$(BENCH_OUT)" $(ARGS)

.PHONY: help
help:
	@printf '%s\n' \
	  'Available commands:' \
	  '  frontend-build Build frontend static files' \
	  '  potential-engine Build the C++ grounding-potential engine' \
	  '  potential-engine-profile Profile solver phases (ARGS=..., PROFILE_OUT=...)' \
	  '  free-geometry-benchmark Compare L1, L2 and L2+ on seeded drawn geometries (ARGS=..., BENCH_OUT=...)' \
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
	  '  smoke-local    Verify frontend, health per component and templates (temporary viewer)' \
	  '  templates      Regenerate the soil-resistivity templates seeded into MinIO' \
	  '  sync-prompts   Publish new Langfuse prompt versions with the staging label' \
	  '  eval-extraction Evaluate document extraction against the gold set (ARGS=...)'

.PHONY: local-up local-down local-build test lint

.PHONY: frontend-build frontend-up frontend-down potential-engine potential-engine-profile free-geometry-benchmark
potential-engine:
	mkdir -p services/potential_engine/build
	g++ -std=c++17 -O3 -Wall -Wextra -Wpedantic services/potential_engine/src/main.cpp -o services/potential_engine/build/spat-potential-engine

PROFILE_OUT ?= /tmp/grounding-potential-engine-profile.json
potential-engine-profile: potential-engine
	python3 services/potential_engine/validation/profile_solver.py --engine services/potential_engine/build/spat-potential-engine --json "$(PROFILE_OUT)" $(ARGS)

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

.PHONY: local-config migrate create-admin sync-prompts smoke-local templates eval-extraction
local-config:
	docker run --rm --name grounding-design-ai-config -v "$(CURDIR):/workspace" -w /workspace python:3.12-alpine python scripts/configure_local.py

migrate:
	$(COMPOSE) run --rm migrate

create-admin:
	$(COMPOSE) exec api python -m src.infrastructure.entrypoint.bootstrap_admin

sync-prompts:
	$(COMPOSE) run --rm --no-deps agent-worker python scripts/sync_langfuse_prompts.py

eval-extraction:
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/workspace" -w /workspace --entrypoint python document-worker scripts/evaluate_extraction.py $(ARGS)

.PHONY: smoke-auth
smoke-auth:
	$(COMPOSE) exec -T api python -m scripts.smoke_auth

smoke-local:
	python3 scripts/smoke_local.py

# Regenerates resources/minio/plantillas-medicion; `make local-up` mirrors it into MinIO.
templates:
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/workspace" -w /workspace --entrypoint python document-worker scripts/generate_measurement_templates.py
	$(COMPOSE) up -d --force-recreate minio-init
