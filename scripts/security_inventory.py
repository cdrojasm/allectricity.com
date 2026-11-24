#!/usr/bin/env python3
"""Create immutable-image SBOMs and vulnerability reports with pinned Syft/Grype versions."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SYFT_VERSION = "1.57.2"
GRYPE_VERSION = "0.122.1"
DOCKER_TOOLS = False
SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def run(args, *, stdout=None):
    command = args
    if DOCKER_TOOLS and args[0] in ("syft", "grype"):
        tool, *tool_args = args
        version = SYFT_VERSION if tool == "syft" else GRYPE_VERSION
        command = ["docker", "run", "--rm", "-v", f"{Path.cwd()}:{Path.cwd()}", "-w", str(Path.cwd()),
                   "-v", "security-grype-db:/.cache/grype"]
        if tool == "syft" and any(str(arg).startswith("docker:") for arg in tool_args):
            docker_socket = os.environ.get("DOCKER_HOST", "unix://" + str(Path.home() / ".docker/run/docker.sock"))
            if docker_socket.startswith("unix://"):
                command.extend(["-v", f"{docker_socket.removeprefix('unix://')}:/var/run/docker.sock",
                                "-e", "DOCKER_HOST=unix:///var/run/docker.sock"])
        command.extend([f"anchore/{tool}:v{version}", *tool_args])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE if stdout is None else stdout,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}")
    return result


def tool_version(tool):
    result = run([tool, "version"])
    return (result.stdout + result.stderr).strip()


def validate_tools():
    syft = tool_version("syft")
    grype = tool_version("grype")
    if not re.search(rf"\b{re.escape(SYFT_VERSION)}\b", syft):
        raise RuntimeError(f"Syft version must be {SYFT_VERSION}; found: {syft}")
    if not re.search(rf"\b{re.escape(GRYPE_VERSION)}\b", grype):
        raise RuntimeError(f"Grype version must be {GRYPE_VERSION}; found: {grype}")
    try:
        db = run(["grype", "db", "status"])
    except RuntimeError as exc:
        if "database does not exist" not in str(exc):
            raise
        run(["grype", "db", "update"])
        db = run(["grype", "db", "status"])
    return {"syft": syft, "grype": grype, "grype_database": (db.stdout + db.stderr).strip()}


def parse_image(value, allow_mutable):
    if "=" not in value:
        raise ValueError(f"Expected SERVICE=IMAGE, got {value!r}")
    service, image = value.split("=", 1)
    if not SERVICE_RE.fullmatch(service) or not image:
        raise ValueError(f"Invalid service or image reference: {value!r}")
    immutable = bool(DIGEST_RE.search(image))
    if not immutable and not allow_mutable:
        raise ValueError(f"{service}: image must end with @sha256:<64 hex chars>: {image}")
    return service, image, immutable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="append", default=[], metavar="SERVICE=IMAGE",
                        help="image reference to inventory; pass one for each deployed service/digest")
    parser.add_argument("--output-root", default="artifacts/security")
    parser.add_argument("--rescan", action="store_true",
                        help="rescan archived SBOMs against Grype's current vulnerability database")
    parser.add_argument("--allow-mutable", action="store_true",
                        help="allow tags for exploratory local scans; not suitable for release inventory")
    parser.add_argument("--docker-tools", action="store_true",
                        help="run the pinned Syft and Grype versions through Docker")
    args = parser.parse_args()
    global DOCKER_TOOLS
    DOCKER_TOOLS = args.docker_tools
    if not args.image and not args.rescan:
        parser.error("pass at least one --image SERVICE=IMAGE")
    if args.image and args.rescan:
        parser.error("--image and --rescan are separate operations")

    try:
        tools = validate_tools()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        try:
            commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
            working_tree_dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())
        except (OSError, RuntimeError):
            commit = None
            working_tree_dirty = None
        out_dir = Path(args.output_root) / ("rescans" if args.rescan else "") / f"{timestamp}-{(commit or 'no-git')[:12]}"
        out_dir.mkdir(parents=True, exist_ok=False)

        if args.rescan:
            sboms = [path for path in Path(args.output_root).rglob("*.cdx.json")
                     if "rescans" not in path.parts]
            if not sboms:
                raise ValueError(f"No archived CycloneDX SBOMs found below {args.output_root}")
            for sbom_path in sboms:
                service = sbom_path.name.removesuffix(".cdx.json")
                scan_name = f"{service}__{sbom_path.parent.name}"
                report_path = out_dir / f"{scan_name}.grype.json"
                with report_path.open("w", encoding="utf-8") as report:
                    run(["grype", f"sbom:{sbom_path}", "--sort-by", "kev", "-o", "json"], stdout=report)
                metadata = {
                    "service": service,
                    "source_sbom": str(sbom_path),
                    "commit": commit,
                    "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
                    "tools": tools,
                    "vulnerability_report": report_path.name,
                }
                Path(f"{out_dir / scan_name}.metadata.json").write_text(
                    json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
                )
                print(f"{service}: {report_path}")
            print(f"Rescan written to {out_dir}")
            return 0

        images = [parse_image(value, args.allow_mutable) for value in args.image]
        names = [service for service, _, _ in images]
        if len(names) != len(set(names)):
            raise ValueError("service names must be unique within one inventory run")

        for service, image, immutable in images:
            stem = out_dir / service
            sbom_path = Path(f"{stem}.cdx.json")
            report_path = Path(f"{stem}.grype.json")
            local_image_id = None
            if image.startswith("docker:"):
                local_image_id = run(["docker", "image", "inspect", image.removeprefix("docker:"),
                                      "--format", "{{.Id}}"])
                local_image_id = local_image_id.stdout.strip()
            run(["syft", image, "--source-name", service, "-o", f"cyclonedx-json={sbom_path}"])
            with report_path.open("w", encoding="utf-8") as report:
                run(["grype", f"sbom:{sbom_path}", "--sort-by", "kev", "-o", "json"], stdout=report)
            metadata = {
                "service": service,
                "image": image,
                "source_type": ("local rebuilt Docker image" if image.startswith("docker:")
                                else "local source directory" if image.startswith("dir:")
                                else "registry image"),
                "local_image_id": local_image_id,
                "immutable_digest_reference": immutable,
                "commit": commit,
                "working_tree_dirty": working_tree_dirty,
                "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
                "tools": tools,
                "sbom": sbom_path.name,
                "vulnerability_report": report_path.name,
            }
            Path(f"{stem}.metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            print(f"{service}: {sbom_path} · {report_path}")
        print(f"Inventory written to {out_dir}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"security inventory: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
