COMPOSE = docker compose --env-file .env -f deploy/local/docker/docker-compose.yml

.DEFAULT_GOAL := help

BENCH_OUT ?= /tmp/free-geometry-benchmark.json
free-geometry-benchmark: potential-engine
	python3 services/potential_engine/validation/free_geometry_benchmark.py --json "$(BENCH_OUT)" $(ARGS)

OPT_BENCH_OUT ?= /tmp/optimizer-benchmark.json
optimizer-benchmark: potential-engine
	python3 services/potential_engine/validation/topology_optimizer_benchmark.py --json "$(OPT_BENCH_OUT)" $(ARGS)

.PHONY: help
help:
	@printf '%s\n' \
	  'Available commands:' \
	  '  frontend-build Build frontend static files' \
	  '  potential-engine Build the C++ grounding-potential engine' \
	  '  potential-engine-profile Profile solver phases (ARGS=..., PROFILE_OUT=...)' \
	  '  free-geometry-benchmark Compare L1, L2 and L2+ on seeded drawn geometries (ARGS=..., BENCH_OUT=...)' \
	  '  optimizer-benchmark Compare optimizer strategies on equal budgets (ARGS=..., OPT_BENCH_OUT=...)' \
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
	  '  smoke-ui-seed  Create one local test user per profile (dev only) in app/.env.smoke-ui' \
	  '  smoke-ui       Browser smoke test through the GUI, one user per profile (SMOKE_* env vars)' \
	  '  smoke-ui-sweep Delete leftover zz-smoke-* projects through the GUI' \
	  '  smoke-local    Verify frontend, health per component and templates (temporary viewer)' \
	  '  templates      Regenerate the soil-resistivity templates seeded into MinIO' \
	  '  sync-prompts   Publish prompt seeds as new Phoenix versions tagged staging' \
	  '  phoenix-openrouter OpenRouter provider + every model with prices in Phoenix' \
	  '  eval-extraction Evaluate document extraction against the gold set (ARGS=...)'

.PHONY: local-up local-down local-build test lint

.PHONY: frontend-build frontend-up frontend-down potential-engine potential-engine-profile free-geometry-benchmark optimizer-benchmark
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

# Test workers: one per core the Docker engine has, but never more than one per GiB of its memory (each worker
# can hold an engine process of its own). The tests are CPU-bound, so more workers than cores would not be faster.
# `worksteal` lets an idle worker take tests from a busy one, and tests/conftest.py starts the slowest first. Measured on
# 15 cores: 30 or 45 workers were no faster (127 s, 155 s) than 15 (91 s with worksteal); serially it takes about 400 s.
# TEST_ARGS='tests/domain/test_topology_search.py -k time' narrows the run. Override with TEST_WORKERS=N; TEST_WORKERS=0 runs serially. Each database test uses its own schema, so they are safe.
TEST_WORKERS ?= $(shell docker info --format '{{.NCPU}} {{.MemTotal}}' 2>/dev/null | awk '{c=$$1; m=int($$2/1073741824); if (m<c) c=m; if (c<1) c=1; print c}')
test:
	$(COMPOSE) --profile test build tests
	$(COMPOSE) --profile test run --rm tests python -m pytest -q -p no:cacheprovider -n $(TEST_WORKERS) --dist worksteal $(TEST_ARGS)

lint:
	$(COMPOSE) --profile test build tests
	$(COMPOSE) --profile test run --rm --no-deps tests ruff check --no-cache src tests --select E9,F63,F7,F82

.PHONY: local-config migrate create-admin sync-prompts phoenix-openrouter smoke-local templates eval-extraction
local-config:
	docker run --rm --name grounding-design-ai-config -v "$(CURDIR):/workspace" -w /workspace python:3.12-alpine python scripts/configure_local.py

migrate:
	$(COMPOSE) run --rm migrate

create-admin:
	$(COMPOSE) exec api python -m src.infrastructure.entrypoint.bootstrap_admin

# OpenRouter in Phoenix: custom provider + every model with its price (re-run to pick up new models).
phoenix-openrouter:
	OPENROUTER_API_KEY=$$(sed -n 's/^OPENROUTER_API_KEY=//p' .env) PHOENIX_ENDPOINT=$${PHOENIX_ENDPOINT:-http://localhost:$${PHOENIX_PORT:-6016}} python3 scripts/phoenix_openrouter.py

# PHOENIX_SEED_TAG=production publishes straight to what the app reads (default: staging, for review).
PHOENIX_SEED_TAG ?= staging
# PHOENIX_SEED_MODEL=<openrouter id> moves every application to that model (default: keep each one's).
PHOENIX_SEED_MODEL ?=
# PHOENIX_SEED_ONLY=spat-study-writer,... limits the run to those applications.
PHOENIX_SEED_ONLY ?=
# PHOENIX_SEED_REASONING=low|medium|high sets the reasoning effort of those versions (none removes it).
PHOENIX_SEED_REASONING ?=
sync-prompts:
	$(COMPOSE) run --rm --no-deps -e PHOENIX_SEED_TAG=$(PHOENIX_SEED_TAG) -e PHOENIX_SEED_MODEL=$(PHOENIX_SEED_MODEL) -e PHOENIX_SEED_ONLY=$(PHOENIX_SEED_ONLY) -e PHOENIX_SEED_REASONING=$(PHOENIX_SEED_REASONING) \
	  -v $(CURDIR)/scripts/sync_phoenix_prompts.py:/app/scripts/sync_phoenix_prompts.py:ro \
	  -v $(CURDIR)/prompts:/app/prompts:ro agent-worker python scripts/sync_phoenix_prompts.py

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

# GUI smoke test: logs in as each profile from SMOKE_<ROLE>_EMAIL/_PASSWORD and drives the real UI.
# Against a non-local URL it also needs SMOKE_CONFIRM_REMOTE=yes. ARGS narrows the run (e.g. ARGS='-g "ciclo"').
.PHONY: smoke-ui-seed smoke-ui smoke-ui-sweep
backup-local:
	sh scripts/backup_local.sh backup

backup-verify:
	sh scripts/backup_local.sh verify $(BACKUP)

smoke-ui-seed:
	node app/smoke-ui/seed-local-users.mjs

smoke-ui:
	cd app && npx playwright test -c smoke-ui/playwright.smoke.config.js --grep-invert @sweep $(ARGS)

smoke-ui-sweep:
	cd app && npx playwright test -c smoke-ui/playwright.smoke.config.js --grep @sweep $(ARGS)
