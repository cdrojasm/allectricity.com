"""Smoke-test the local deployment through the published URL, the way the browser uses it.

1. Frontend: index.html and the JS/CSS bundles it references.
2. Public probes: /health (liveness) and /ready (database initialised).
3. Authenticated (unless --public-only): a temporary viewer is created inside the API
   container, logs in through nginx, requires every required component of
   /api/v1/system/health to be "ok", lists the resistivity templates and downloads each file
   through its presigned MinIO URL. The viewer is disabled afterwards, so runs are repeatable.

    python3 scripts/smoke_local.py [--public-only]     # or: make smoke-local
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".env"), "-f",
           str(ROOT / "deploy/local/docker/docker-compose.yml")]
RETRIES = 30


class SmokeFailure(RuntimeError):
    pass


def fetch(url, *, token=None, data=None, retries=1):
    """GET (or POST JSON) and return (status, headers, body); retries connection errors and 5xx."""
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    last = None
    for attempt in range(retries):
        try:
            with urlopen(Request(url, data=body, headers=headers), timeout=10) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            last = SmokeFailure(f"{url} devolvió HTTP {exc.code}: {exc.read(300).decode(errors='replace')}")
            if exc.code < 500:
                raise last from exc
        except (TimeoutError, URLError) as exc:
            last = SmokeFailure(f"{url} no responde: {exc}")
        if attempt < retries - 1:
            time.sleep(2)
    raise last


def fetch_json(url, **kwargs):
    return json.loads(fetch(url, **kwargs)[2])


def frontend_port():
    port = os.getenv("SPAT_FRONTEND_PORT")
    env_file = ROOT / ".env"
    if not port and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("SPAT_FRONTEND_PORT="):
                port = line.split("=", 1)[1].strip()
    return port or "3001"


def check_frontend(base):
    _, _, html = fetch(base + "/", retries=RETRIES)
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html.decode())
    if not assets:
        raise SmokeFailure("index.html no referencia bundles en /assets (¿falta make frontend-build?)")
    for asset in assets:
        fetch(base + asset)
    return f"index.html y {len(assets)} bundles"


def check_health(base):
    body = fetch_json(base + "/health", retries=RETRIES)
    if body.get("status") != "ok":
        raise SmokeFailure(f"/health respondió {body}")
    return body.get("service", "ok")


def check_ready(base):
    for attempt in range(RETRIES):
        try:
            if fetch_json(base + "/ready").get("status") == "ready":
                return "ready"
        except SmokeFailure:
            pass
        time.sleep(2)
    raise SmokeFailure("/ready no reportó ready")


def compose_exec(*args):
    result = subprocess.run([*COMPOSE, "exec", "-T", "api", "python", "-m", "scripts.smoke_session", *args],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SmokeFailure(f"smoke_session {args[0]} falló: {result.stderr.strip()[-400:]}")
    return result.stdout


def check_system_health(base, token):
    body = fetch_json(base + "/api/v1/system/health", token=token)
    failing = [f"{c['label']}: {c['detail']}" for c in body["components"]
               if c["required"] and c["status"] != "ok"]
    if failing:
        raise SmokeFailure("componentes con fallo → " + "; ".join(failing))
    return ", ".join(f"{c['id']} {c['latency_ms']}ms" for c in body["components"] if c["status"] == "ok")


def check_templates(base, token):
    items = fetch_json(base + "/api/v1/plantillas-medicion", token=token)["items"]
    if not items:
        raise SmokeFailure("el catálogo de plantillas está vacío")
    downloaded = 0
    for template in items:
        for entry in template["files"]:
            link = fetch_json(f"{base}/api/v1/plantillas-medicion/{template['id']}/{entry['format']}", token=token)
            _, headers, content = fetch(link["url"])
            if entry["format"] == "xlsx" and not content.startswith(b"PK"):
                raise SmokeFailure(f"{entry['filename']} no es un XLSX válido")
            if entry["format"] == "csv" and b";" not in content.splitlines()[0]:
                raise SmokeFailure(f"{entry['filename']} no tiene encabezados CSV")
            if entry["filename"] not in headers.get("Content-Disposition", ""):
                raise SmokeFailure(f"{entry['filename']} no se descarga con su nombre de archivo")
            downloaded += 1
    return f"{len(items)} métodos, {downloaded} archivos descargados desde MinIO"


def main(argv):
    base = f"http://127.0.0.1:{frontend_port()}"
    steps = [("frontend", check_frontend), ("liveness /health", check_health), ("readiness /ready", check_ready)]
    failures = 0

    def run(label, step, *args):
        nonlocal failures
        try:
            print(f"OK   {label}: {step(base, *args)}")
            return True
        except (SmokeFailure, KeyError, ValueError) as exc:
            failures += 1
            print(f"FAIL {label}: {exc}", file=sys.stderr)
            return False

    for label, step in steps:
        run(label, step)
    if "--public-only" in argv:
        return 1 if failures else 0
    if failures:
        print("SKIP verificaciones autenticadas: la parte pública falló", file=sys.stderr)
        return 1

    try:
        session = json.loads(compose_exec("create"))
    except (SmokeFailure, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL sesión temporal: {exc}", file=sys.stderr)
        return 1
    try:
        tokens = fetch_json(base + "/api/v1/auth/login",
                            data={"email": session["email"], "password": session["password"]})
        print("OK   login vía nginx: usuario temporal viewer")
        run("salud por componente", check_system_health, tokens["access_token"])
        run("plantillas de resistividad", check_templates, tokens["access_token"])
    except SmokeFailure as exc:
        failures += 1
        print(f"FAIL login vía nginx: {exc}", file=sys.stderr)
    finally:
        try:
            compose_exec("cleanup", session["user_id"])
        except (SmokeFailure, subprocess.TimeoutExpired) as exc:
            print(f"WARN no se pudo desactivar el usuario temporal: {exc}", file=sys.stderr)
    print("Smoke test " + ("FALLÓ" if failures else "OK"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
