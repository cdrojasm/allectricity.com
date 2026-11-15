"""SV-27: frozen results of the reference cases, one record per case and solver version.

`frozen_results.json` holds, for every case in `reference_cases.json`, the values the engine produced for each
check, the segment count, the backward error and the solver version. The test
`tests/infrastructure/test_frozen_results.py` recomputes them and fails on any difference beyond floating-point
noise: a change in the numbers must be explained, not absorbed.

Regeneration rule (BACKLOG_SOLVER SV-27): the file is rewritten only together with a change of `kSolverVersion`
in `src/main.cpp`, and the change is recorded in PE-04. The script refuses to overwrite a record of the same
solver version unless `--force` is given, which is meant for a first freeze or for a documented correction.

    python3 services/potential_engine/validation/freeze_results.py            # report differences, write nothing
    python3 services/potential_engine/validation/freeze_results.py --write    # add the record of a new solver version
    python3 services/potential_engine/validation/freeze_results.py --write --force --reason "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient  # noqa: E402
from src.infrastructure.calculations.potential_engine_validation import evaluate_case, load_cases  # noqa: E402

FROZEN_PATH = Path(__file__).resolve().parent / "frozen_results.json"
DEFAULT_CASES_PATH = Path(__file__).resolve().parent / "reference_cases.json"
# Differences the test tolerates: floating-point noise between compilers and platforms, never a model change.
VALUE_TOLERANCE_REL = 1e-7
BACKWARD_ERROR_CEILING = 1e-9


def compute(client: PotentialEngineClient, cases: dict) -> dict:
    records = {}
    version = None
    for case in cases["cases"]:
        run = evaluate_case(client, case)
        version = run["trace"]["solver_version"]
        records[case["id"]] = {
            "values": [{"quantity": check["quantity"], "label": check.get("label"), "value": value}
                       for check, value in zip(case["checks"], run["values"])],
            "segment_count": run["segment_count"], "point_count": run["point_count"],
            "backward_error": run["diagnostics"].get("backward_error"),
        }
    return {"solver_version": version, "cases": records}


def load_frozen(path: Path = FROZEN_PATH) -> dict:
    if not path.exists():
        return {"schema_version": "spat.frozen-results/1.0", "rule": "", "records": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def latest_record(frozen: dict, solver_version: str | None = None) -> dict | None:
    records = frozen.get("records") or []
    if solver_version is not None:
        records = [r for r in records if r["solver_version"] == solver_version]
    return records[-1] if records else None


def differences(frozen_record: dict, current: dict) -> list[str]:
    """Human-readable differences between a frozen record and a fresh computation."""
    out = []
    if frozen_record["solver_version"] != current["solver_version"]:
        out.append(f"solver version {frozen_record['solver_version']} -> {current['solver_version']}")
    for case_id, record in current["cases"].items():
        frozen_case = frozen_record["cases"].get(case_id)
        if frozen_case is None:
            out.append(f"{case_id}: not frozen")
            continue
        if frozen_case["segment_count"] != record["segment_count"]:
            out.append(f"{case_id}: segment count {frozen_case['segment_count']} -> {record['segment_count']}")
        for old, new in zip(frozen_case["values"], record["values"]):
            scale = max(abs(old["value"]), abs(new["value"]), 1e-300)
            if abs(old["value"] - new["value"]) / scale > VALUE_TOLERANCE_REL:
                out.append(f"{case_id}: {old['label'] or old['quantity']} {old['value']:.10g} -> {new['value']:.10g}")
        if len(frozen_case["values"]) != len(record["values"]):
            out.append(f"{case_id}: {len(frozen_case['values'])} checks frozen, {len(record['values'])} computed")
        if record["backward_error"] is not None and record["backward_error"] > BACKWARD_ERROR_CEILING:
            out.append(f"{case_id}: backward error {record['backward_error']:.3g} above {BACKWARD_ERROR_CEILING:g}")
    for case_id in frozen_record["cases"]:
        if case_id not in current["cases"]:
            out.append(f"{case_id}: frozen but no longer a reference case")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="append the record for the current solver version")
    parser.add_argument("--force", action="store_true", help="replace an existing record of the same solver version")
    parser.add_argument("--reason", default="", help="why the record is (re)written; stored with it")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--out", default=str(FROZEN_PATH))
    args = parser.parse_args(argv)

    client = PotentialEngineClient()
    if not Path(client.executable).is_file():
        print(f"engine not built at {client.executable}; run `make potential-engine`", file=sys.stderr)
        return 2
    current = compute(client, load_cases(args.cases))
    out_path = Path(args.out)
    frozen = load_frozen(out_path)
    existing = latest_record(frozen, current["solver_version"])
    if existing:
        diff = differences(existing, current)
        print(f"solver {current['solver_version']}: " + ("no differences" if not diff else f"{len(diff)} difference(s)"))
        for line in diff:
            print("  " + line)
    else:
        print(f"solver {current['solver_version']}: no frozen record yet")
    if not args.write:
        return 0 if (existing and not differences(existing, current)) else 1
    if existing and not args.force:
        print("a record of this solver version exists; change kSolverVersion or pass --force with --reason", file=sys.stderr)
        return 2
    if args.force and not args.reason.strip():
        print("--force needs --reason", file=sys.stderr)
        return 2
    record = {**current, "frozen_on": date.today().isoformat(), "reason": args.reason.strip() or "new solver version"}
    frozen["records"] = [r for r in frozen.get("records") or [] if r["solver_version"] != current["solver_version"]] + [record]
    frozen["rule"] = ("Records are added only with a change of kSolverVersion (recorded in PE-04); a record of the same "
                      "version is replaced only with --force and a reason. Any difference the test reports must be explained.")
    out_path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(record['cases'])} cases, solver {current['solver_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
