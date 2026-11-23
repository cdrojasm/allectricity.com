#!/usr/bin/env python3
"""Which Railway services a set of changed files has to rebuild.

    git diff --name-only <deployed>..<head> | python3 deploy/railway/changed_services.py
    python3 deploy/railway/changed_services.py --range <base> <head>    # diff + [deploy: ...] labels
    python3 deploy/railway/changed_services.py --ci <base> <head>       # does CI need the backend suite?
    python3 deploy/railway/changed_services.py --self-test

Commit labels (anywhere in any commit message of the range; they only ADD work, never remove it):
    [ci: full]              run the backend suite even if the diff does not need it
    [deploy: api frontend]  deploy these services too;  [deploy: all] = every service
A label that asks for less than the diff needs changes nothing: the diff always wins.

Prints the services, space separated, in deploy order (api first: it applies the migrations on start).
Each file takes the FIRST rule that matches it, so a narrow rule (the API routes) goes before a broad one
(all of backend/src). A file no rule knows is reported on stderr and deploys nothing; add a rule for it.
"""

import re
import subprocess
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


# Files that cannot break the backend suite: with only these in the range, CI skips lint and the backend tests.
# An allowlist on purpose: a file nobody listed here (a new folder, tests/, the Makefile, dependencies/) runs them.
NO_BACKEND_TESTS = (
    "app/", "docs/", "backups/", "test-results/", "README", "AGENTS.md", "CLAUDE.md", ".gitignore",
    "deploy/railway/Dockerfile.frontend", "deploy/railway/nginx.conf.template", "deploy/railway/Dockerfile.minio",
    "deploy/railway/minio-start.sh", "deploy/railway/README.md", "deploy/railway/changed_services.py",
    "deploy/railway/deploy_services.py", ".github/workflows/deploy.yml", "resources/minio/",
)

LABEL = re.compile(r"\[(ci|deploy):\s*([^\]]*)\]", re.IGNORECASE)


def labels(messages):
    """(ci_full, services to deploy, warnings) from the [ci: ...] and [deploy: ...] labels in commit messages."""
    ci_full, deploy, warnings = False, set(), []
    for kind, value in LABEL.findall(messages):
        words = value.lower().split()
        if kind.lower() == "ci":
            if words == ["full"]:
                ci_full = True
            else:
                warnings.append(f"Etiqueta [ci: {value}] desconocida; la única es [ci: full].")
            continue
        for word in words:
            if word == "all":
                deploy.update(ORDER)
            elif word in ORDER:
                deploy.add(word)
            else:
                warnings.append(f"Servicio desconocido en [deploy: {value}]: {word}.")
    return ci_full, deploy, warnings


def needs_backend_tests(paths):
    return any(p.strip() and not p.strip().startswith(NO_BACKEND_TESTS) for p in paths)


def _git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _range(base, head):
    """(changed paths, commit messages) between base and head, both inclusive of every commit in the range."""
    return _git("diff", "--name-only", base, head).splitlines(), _git("log", "--format=%B", f"{base}..{head}")


def _warn(lines):
    for line in lines:
        print(f"::warning::{line}", file=sys.stderr)


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

    assert not needs_backend_tests(["app/src/App.jsx", "docs/a.md", "deploy/railway/Dockerfile.frontend.dockerignore"])
    assert not needs_backend_tests([".github/workflows/deploy.yml", "CLAUDE.md", ""])
    for path in ("backend/src/x.py", "tests/test_x.py", "Makefile", "dependencies/requirements.txt",
                 "services/potential_engine/src/main.cpp", ".github/workflows/ci.yml", "something/new.txt"):
        assert needs_backend_tests(["app/src/App.jsx", path]), path

    assert labels("fix [ci: full]\n\nfeat [deploy: api frontend]\n[deploy: ocr]") == (
        True, {"api", "frontend", "ocr"}, [])
    assert labels("[Deploy: ALL]")[1] == set(ORDER)
    assert labels("sin etiquetas") == (False, set(), [])
    ci_full, deploy, warnings = labels("[deploy: api fronted] [ci: fast]")
    assert not ci_full and deploy == {"api"} and len(warnings) == 2
    print(f"changed_services: {len(cases) + 1} casos de mapeo + etiquetas y CI OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    if len(sys.argv) == 4 and sys.argv[1] in ("--range", "--ci"):
        paths, messages = _range(sys.argv[2], sys.argv[3])
        ci_full, deploy, warnings = labels(messages)
        _warn(warnings)
        if sys.argv[1] == "--ci":                       # key=value lines for $GITHUB_OUTPUT
            by_diff = needs_backend_tests(paths)
            reason = ("cambios que afectan el backend" if by_diff else
                      "etiqueta [ci: full]" if ci_full else "solo frontend/docs/deploy: se omite la suite backend")
            print(f"backend={'true' if by_diff or ci_full else 'false'}")
            print(f"reason={reason}")
            sys.exit(0)
        services, unknown = services_for(paths)
        _warn(f"Sin regla de despliegue para {p}; no se despliega nada por él." for p in unknown)
        print(" ".join(s for s in ORDER if s in set(services) | deploy))
        sys.exit(0)
    services, unknown = services_for(sys.stdin.read().splitlines())
    for path in unknown:
        print(f"::warning::Sin regla de despliegue para {path}; no se despliega nada por él.", file=sys.stderr)
    print(" ".join(services))
