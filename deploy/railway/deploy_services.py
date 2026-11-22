#!/usr/bin/env python3
"""Deploy Railway services from the current checkout and wait until each one is live.

    RAILWAY_TOKEN=<project token> python3 deploy/railway/deploy_services.py api frontend ...

The api goes first and alone: it applies the database migrations before it starts serving, and the
other services may need the new schema. The rest are uploaded together and then awaited. The script
exits non-zero if any deployment does not reach SUCCESS, naming which and with its Railway link.
"""

import json
import re
import subprocess
import sys
import time

TERMINAL_FAIL = {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}
TIMEOUT_S = 25 * 60
POLL_S = 15


def railway(*args):
    return subprocess.run(["railway", *args], capture_output=True, text=True)


def upload(service):
    """Start a deployment of the checkout; return its id (from the URL the CLI prints)."""
    out = railway("up", ".", "--path-as-root", "-s", service, "--detach")
    text = out.stdout + out.stderr
    match = re.search(r"[?&]id=([0-9a-f-]{36})", text)
    if out.returncode != 0 or not match:
        raise SystemExit(f"::error::No se pudo subir {service}:\n{text.strip()}")
    print(f"→ {service}: despliegue {match.group(1)} iniciado", flush=True)
    return match.group(1), (re.search(r"https://railway\.com/\S+", text) or [None])[0]


def status(service):
    out = railway("service", "status", "-s", service, "--json")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}                                  # a transient CLI/API error: poll again


def wait(deployments):
    """deployments: {service: (deployment_id, url)}. Returns {service: final status}."""
    pending, final, started = dict(deployments), {}, time.monotonic()
    while pending and time.monotonic() - started < TIMEOUT_S:
        time.sleep(POLL_S)
        for service, (deployment_id, url) in list(pending.items()):
            current = status(service)
            if current.get("deploymentId") != deployment_id:
                continue                           # Railway still reports the previous deployment
            state = current.get("status", "")
            if state == "SUCCESS" or state in TERMINAL_FAIL:
                final[service] = state
                print(f"{'✓' if state == 'SUCCESS' else '✗'} {service}: {state}" + ("" if state == "SUCCESS" else f" · {url}"), flush=True)
                del pending[service]
    for service in pending:
        final[service] = "TIMEOUT"
        print(f"✗ {service}: sin terminar tras {TIMEOUT_S // 60} min · {pending[service][1]}", flush=True)
    return final


KNOWN = {"api", "scheduler", "agent-worker", "document-worker", "calculation-worker", "optimizer-worker",
         "mail-worker", "render-worker", "potential-engine", "ocr", "minio", "frontend"}


def main(services):
    unknown = [s for s in services if s not in KNOWN]
    if unknown:
        print(f"::error::Servicios desconocidos: {' '.join(unknown)}. Válidos: {' '.join(sorted(KNOWN))}")
        return 2
    if not services:
        print("Nada que desplegar.")
        return 0
    results = {}
    if "api" in services:
        results |= wait({"api": upload("api")})
        if results["api"] != "SUCCESS":
            print("::error::El api no quedó en SUCCESS; no se despliega el resto (podría necesitar las migraciones).")
            return 1
    rest = [s for s in services if s != "api"]
    if rest:
        results |= wait({service: upload(service) for service in rest})
    failed = [s for s, state in results.items() if state != "SUCCESS"]
    if failed:
        print(f"::error::Fallaron: {' '.join(failed)}")
        return 1
    print(f"Desplegados: {' '.join(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
