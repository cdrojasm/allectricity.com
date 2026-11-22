#!/usr/bin/env python3
"""Which Railway services a set of changed files has to rebuild.

    git diff --name-only <deployed>..<head> | python3 deploy/railway/changed_services.py
    python3 deploy/railway/changed_services.py --self-test

Prints the services, space separated, in deploy order (api first: it applies the migrations on start).
Each file takes the FIRST rule that matches it, so a narrow rule (the API routes) goes before a broad one
(all of backend/src). A file no rule knows is reported on stderr and deploys nothing; add a rule for it.
"""

import sys

WORKERS = ["agent-worker", "document-worker", "calculation-worker", "optimizer-worker", "mail-worker", "render-worker"]
BACKEND = ["api", "scheduler", *WORKERS]          # same code (backend/src) in two images: Dockerfile.api and .worker
ORDER = ["api", "scheduler", *WORKERS, "potential-engine", "ocr", "minio", "frontend"]

RULES = [
    # Nothing to rebuild: tests, docs, CI, evaluation data, smoke and e2e specs.
    (("tests/", "docs/", "evaluation/", "backups/", "test-results/", ".github/", "app/smoke-ui/", "app/e2e/",
      "app/tests/", "README", "AGENTS.md", "CLAUDE.md", "pytest.ini", ".gitignore"), []),
    # Routes run only in the api; the one exception is schemas.py, which the design agent imports.
    (("backend/src/infrastructure/entrypoint/api/schemas.py",), ["api", "agent-worker"]),
    (("backend/src/infrastructure/entrypoint/api/",), ["api"]),
    # Only the api runs migrations (RUN_MIGRATIONS=true), before it starts serving.
    (("backend/migrations/", "backend/alembic.ini"), ["api"]),
    (("backend/src/", "prompts/", "dependencies/"), BACKEND),
    (("deploy/local/docker/Dockerfile.api",), ["api", "scheduler"]),
    (("deploy/local/docker/Dockerfile.worker",), WORKERS),
    (("scripts/smoke_session.py",), ["api", "scheduler"]),
    (("scripts/sync_phoenix_prompts.py",), WORKERS),
    # The api image compiles the engine too (local fallback), so the C++ source rebuilds both.
    (("services/potential_engine/src/",), ["potential-engine", "api", "scheduler"]),
    (("services/potential_engine/", "deploy/local/docker/Dockerfile.potential-engine"), ["potential-engine"]),
    (("services/ocr/", "deploy/local/docker/Dockerfile.ocr"), ["ocr"]),
    (("app/", "deploy/railway/Dockerfile.frontend", "deploy/railway/nginx.conf.template"), ["frontend"]),
    (("resources/minio/", "deploy/railway/Dockerfile.minio", "deploy/railway/minio-start.sh"), ["minio"]),
    # What every image is built from.
    ((".dockerignore",), ORDER),
    # Deploy tooling and local-only files change no image.
    (("deploy/", "scripts/", "Makefile", "config/", "resources/"), []),
]


def services_for(paths):
    """(services in deploy order, files no rule matched)."""
    chosen, unknown = set(), []
    for path in (p.strip() for p in paths):
        if not path:
            continue
        for prefixes, services in RULES:
            if path.startswith(prefixes):
                chosen.update(services)
                break
        else:
            unknown.append(path)
    return [s for s in ORDER if s in chosen], unknown


def self_test():
    cases = {
        ("backend/src/infrastructure/entrypoint/api/study_routes.py",): ["api"],
        ("backend/src/infrastructure/entrypoint/api/schemas.py",): ["api", "agent-worker"],
        ("backend/migrations/versions/0025_x.py",): ["api"],
        ("backend/src/infrastructure/agents/design_agent.py",): BACKEND,
        ("app/src/components/AgentArtifact.jsx",): ["frontend"],
        ("app/smoke-ui/specs/05-optimizador-topologia.spec.js", "tests/infrastructure/test_x.py", "docs/a.md"): [],
        ("app/src/styles.css", "backend/src/infrastructure/entrypoint/api/job_routes.py"): ["api", "frontend"],
        ("services/potential_engine/src/main.cpp",): ["api", "scheduler", "potential-engine"],
        ("services/potential_engine/server.py",): ["potential-engine"],
        ("services/ocr/main.py",): ["ocr"],
        ("deploy/local/docker/Dockerfile.worker",): WORKERS,
        ("resources/minio/plantillas-medicion/a.xlsx",): ["minio"],
        (".github/workflows/deploy.yml", "deploy/railway/changed_services.py"): [],
    }
    for paths, expected in cases.items():
        got, unknown = services_for(paths)
        assert got == [s for s in ORDER if s in expected] and not unknown, (paths, got, unknown)
    assert services_for(["something/new.txt"]) == ([], ["something/new.txt"])
    print(f"changed_services: {len(cases) + 1} casos OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    services, unknown = services_for(sys.stdin.read().splitlines())
    for path in unknown:
        print(f"::warning::Sin regla de despliegue para {path}; no se despliega nada por él.", file=sys.stderr)
    print(" ".join(services))
