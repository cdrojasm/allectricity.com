#!/usr/bin/env python3
"""Inventory installed Python packages in running Railway services and scan their SBOMs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

SYFT_VERSION = "1.57.2"
GRYPE_VERSION = "0.122.1"
PROJECT = "c87f677d-3c89-4bc5-befd-27f92f042992"
ENVIRONMENT = "production"
DEFAULT_SERVICES = [
    "api", "scheduler", "agent-worker", "calculation-worker", "document-worker",
    "mail-worker", "optimizer-worker", "render-worker", "ocr", "potential-engine",
]
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def run(args, *, stdout=None, check=True):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE if stdout is None else stdout,
                            stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}")
    return result


def docker_tool(tool, *args, stdout=None):
    version = SYFT_VERSION if tool == "syft" else GRYPE_VERSION
    command = ["docker", "run", "--rm", "-v", f"{Path.cwd()}:{Path.cwd()}", "-w", str(Path.cwd()),
               "-v", "security-grype-db:/.cache/grype", f"anchore/{tool}:v{version}", *args]
    return run(command, stdout=stdout)


def deployed_artifact(service):
    result = run(["railway", "deployment", "list", "-s", service, "-e", ENVIRONMENT,
                  "-p", PROJECT, "--limit", "1", "--json"], check=False)
    if result.returncode:
        return {"deployment_id": None, "image_digest": None, "lookup_error": result.stderr.strip()}
    try:
        latest = json.loads(result.stdout)[0]
        return {"deployment_id": latest.get("id"),
                "image_digest": latest.get("meta", {}).get("imageDigest"),
                "deployment_status": latest.get("status")}
    except (IndexError, KeyError, TypeError, ValueError):
        return {"deployment_id": None, "image_digest": None, "lookup_error": "unrecognized Railway response"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", action="append", default=[], help="Railway service to inspect; repeatable")
    parser.add_argument("--output-root", default="artifacts/security")
    args = parser.parse_args()
    services = args.service or DEFAULT_SERVICES
    if len(services) != len(set(services)):
        parser.error("service names must be unique")

    try:
        syft_version = docker_tool("syft", "version").stdout.strip()
        grype_version = docker_tool("grype", "version").stdout.strip()
        if SYFT_VERSION not in syft_version or GRYPE_VERSION not in grype_version:
            raise RuntimeError("Docker scanner image version does not match the pinned version")
        try:
            db = docker_tool("grype", "db", "status").stdout.strip()
        except RuntimeError as exc:
            if "database does not exist" not in str(exc):
                raise
            docker_tool("grype", "db", "update")
            db = docker_tool("grype", "db", "status").stdout.strip()

        timestamp = datetime.now(timezone.utc)
        run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        try:
            commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
            working_tree_dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())
        except RuntimeError:
            commit = None
            working_tree_dirty = None
        out_dir = Path(args.output_root) / f"runtime-{run_id}-{(commit or 'no-git')[:12]}"
        out_dir.mkdir(parents=True, exist_ok=False)
        failures = []

        for service in services:
            print(f"{service}: reading installed pip packages", flush=True)
            artifact = deployed_artifact(service)
            ssh = run(["railway", "ssh", "-p", PROJECT, "-e", ENVIRONMENT, "-s", service,
                       "--", "python", "-m", "pip", "list", "--format=json"], check=False)
            if ssh.returncode:
                failure = {"service": service, "stage": "railway-ssh-pip-list", "error": ssh.stderr.strip()}
                failures.append(failure)
                (out_dir / f"{service}.error.txt").write_text(failure["error"] + "\n", encoding="utf-8")
                print(f"{service}: unavailable ({ssh.stderr.strip().splitlines()[-1:]})", flush=True)
                continue

            try:
                packages = json.loads(ssh.stdout)
                if not isinstance(packages, list):
                    raise ValueError("pip output is not a JSON package list")
                service_dir = out_dir / service
                service_dir.mkdir()
                (service_dir / "pip-list.json").write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")
                requirements = []
                for package in packages:
                    name, version = str(package["name"]), str(package["version"])
                    if not PACKAGE_RE.fullmatch(name) or "\n" in version or "\r" in version:
                        raise ValueError(f"unsafe package record: {package!r}")
                    requirements.append(f"{name}=={version}")
                (service_dir / "requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")
                sbom_path = service_dir / f"{service}.cdx.json"
                report_path = service_dir / f"{service}.grype.json"
                docker_tool("syft", f"dir:{service_dir}", "--source-name", f"railway-runtime-{service}",
                            "-o", f"cyclonedx-json={sbom_path}")
                with report_path.open("w", encoding="utf-8") as report:
                    docker_tool("grype", f"sbom:{sbom_path}", "--sort-by", "kev", "-o", "json", stdout=report)
                metadata = {
                    "service": service,
                    "source_type": "live Railway runtime pip list",
                    "observed_at_utc": timestamp.isoformat(),
                    **artifact,
                    "package_count": len(packages),
                    "os_packages_included": False,
                    "commit": commit,
                    "working_tree_dirty": working_tree_dirty,
                    "tools": {"syft": syft_version, "grype": grype_version, "grype_database": db},
                    "sbom": sbom_path.name,
                    "vulnerability_report": report_path.name,
                }
                (service_dir / f"{service}.metadata.json").write_text(
                    json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
                )
                print(f"{service}: {len(packages)} packages scanned", flush=True)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                failures.append({"service": service, "stage": "sbom-or-grype", "error": str(exc)})
                print(f"{service}: scan failed ({exc})", flush=True)

        result = {"observed_at_utc": timestamp.isoformat(), "services_requested": services,
                  "failures": failures, "status": "partial" if failures else "complete"}
        (out_dir / "runtime-inventory.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Runtime inventory written to {out_dir}", flush=True)
        return 1 if failures else 0
    except (OSError, RuntimeError) as exc:
        print(f"runtime inventory: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
