#!/usr/bin/env python3
"""Export locked Python dependency SBOMs and scan them with the pinned Grype image."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

UV_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
GRYPE_IMAGE = "anchore/grype:v0.122.1"
PROFILES = {
    "api": ("api", "agent", "billing", "parsers"),
    "tests": ("api", "documents", "billing", "dev"),
    "agent-worker": ("agent",),
    "document-worker": ("documents",),
    "calculation-worker": (),
    "mail-worker": ("billing",),
    "render-worker": ("render",),
    "ocr": ("ocr",),
}


def command(args, *, output=None, check=True):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
    if output is not None:
        output.write_text(result.stdout, encoding="utf-8")
    return result.stdout


def main():
    root = Path.cwd()
    timestamp = datetime.now(timezone.utc)
    commit = command(["git", "rev-parse", "HEAD"]).strip()
    output_dir = root / "artifacts/security" / f"locks-{timestamp:%Y%m%dT%H%M%SZ}-{commit[:12]}"
    output_dir.mkdir(parents=True, exist_ok=False)
    mounted_output = Path("/workspace") / output_dir.relative_to(root)
    root_arg = str(root)

    command(["docker", "run", "--rm", "-v", f"{root_arg}:/workspace", "-w", "/workspace",
             UV_IMAGE, "uv", "lock", "--check", "--project", "dependencies"])
    db_args = ["docker", "run", "--rm", "-v", "security-grype-db:/.cache/grype", GRYPE_IMAGE]
    db_status = subprocess.run([*db_args, "db", "status"], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if db_status.returncode and "database does not exist" in (db_status.stdout + db_status.stderr):
        command([*db_args, "db", "update"])
        db_status = subprocess.run([*db_args, "db", "status"], text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if db_status.returncode:
        raise RuntimeError(f"Grype database status failed: {db_status.stderr.strip()}")
    grype_db = db_status.stdout + db_status.stderr

    results = []
    for profile, extras in PROFILES.items():
        sbom_name = f"{profile}.cdx.json"
        report_name = f"{profile}.grype.json"
        export_args = ["uv", "export", "--locked", "--no-dev", "--no-emit-project",
                       "--project", "dependencies", "--format", "cyclonedx1.5",
                       "--output-file", str(mounted_output / sbom_name)]
        for extra in extras:
            export_args.extend(["--extra", extra])
        command(["docker", "run", "--rm", "-v", f"{root_arg}:/workspace", "-w", "/workspace",
                 UV_IMAGE, *export_args])

        report = command(["docker", "run", "--rm", "-v", f"{root_arg}:/workspace", "-w", "/workspace",
                          "-v", "security-grype-db:/.cache/grype", GRYPE_IMAGE,
                          f"sbom:/workspace/{mounted_output.relative_to('/workspace')}/{sbom_name}",
                          "--sort-by", "kev", "-o", "json"])
        (output_dir / report_name).write_text(report, encoding="utf-8")
        parsed = json.loads(report)
        counts = {level: sum(item.get("vulnerability", {}).get("severity") == level
                             for item in parsed.get("matches", []))
                  for level in ("Critical", "High", "Medium", "Low")}
        results.append({"profile": profile, "sbom": sbom_name, "report": report_name,
                        "match_count": len(parsed.get("matches", [])), "severity_counts": counts})
        print(f"{profile}: {counts}", flush=True)

    metadata = {"captured_at_utc": timestamp.isoformat(), "commit": commit,
                "profiles": results, "tools": {"uv_image": UV_IMAGE, "grype_image": GRYPE_IMAGE,
                                                "grype_database": grype_db.strip()}}
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Python lock inventory: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"security lock inventory failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
