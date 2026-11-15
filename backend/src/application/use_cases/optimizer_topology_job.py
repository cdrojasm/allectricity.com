"""The topological optimizer as a product job: queued by the API, run by a worker, read back as alternatives.

Three pieces, kept apart from the search itself (`optimizer_topology_run`):

  rate cards   Every rate the cost needs comes either from an approved, unexpired catalog item in the run's
               currency and the unit the takeoff measures in, or from an explicit amount with a stated source.
               Quantities come from the geometry (`geometry_cost.takeoff`); nothing is defaulted, so a missing
               rate leaves the cost incomplete and the run is refused before the solver is touched.
  execution    `execute_topology_run` moves a queued run to running, resumes from its checkpoint file when a
               worker restarts it, checks for cancellation after every solver verdict, and stores only L3
               finalists as alternatives. A terminal state written by someone else is never overwritten.
  comparison   `compare_alternatives` puts the base design and the alternatives side by side (cost, Rg, Vs, Vt,
               utilization margin, constructive complexity) and marks the cost/utilization Pareto front among
               the validated alternatives. Nothing here is certified; the report says so.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import time
from typing import Any, Callable
from uuid import uuid4

from src.domain.spat import geometry_graph as gg
from src.domain.spat.geometry_cost import evaluate_geometry_cost, takeoff
from src.domain.spat.geometry_operators import OperatorConstraints

TOPOLOGY_ALGORITHM = "topology_alns"
TOPOLOGY_STRATEGY = "alns"   # the official policy (OPT-017); the experimental refinements stay out of the product
FIXED_RATE_KEYS = ("excavation.trench", "installation.conductor", "installation.rod", "installation.connection")
# The unit each takeoff line is measured in, and the catalog quantity units that mean exactly that.
RATE_UNITS = {
    "material.conductor": ("m", {"m"}),
    "material.rod": ("m", {"m"}),
    "excavation.trench": ("m3", {"m3"}),
    "installation.conductor": ("m", {"m"}),
    "installation.rod": ("rod", {"rod", "und", "unidad", "unit"}),
    "installation.connection": ("connection", {"connection", "und", "unidad", "unit"}),
}


class RunCancelled(Exception):
    """Raised from the progress hook when the run was cancelled while the search was running."""


class RateCardError(ValueError):
    pass


def _rate_family(key: str) -> str:
    for family in RATE_UNITS:
        if key == family or key.startswith(family + "."):
            return family
    raise RateCardError(f"unknown rate key {key!r}")


def _amount(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def build_rate_card(rates: dict[str, dict[str, Any]], *, currency: str, trench_width_m: float | None,
                    trench_width_source: str | None, catalog_rows: list[dict[str, Any]],
                    now_epoch_s: int) -> dict[str, Any]:
    """A rate card for `geometry_cost` plus the provenance of every rate in it.

    Each entry of `rates` is either {"catalog_item_id": id} or {"amount": value, "source": text}. A catalog item
    must be approved, unexpired, priced in `currency` and quoted in the unit the takeoff measures that line in.
    """
    catalog = {row["id"]: row for row in catalog_rows if row.get("status") == "approved"}
    card_rates: dict[str, str] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for key, entry in sorted(rates.items()):
        family = _rate_family(key)
        unit, accepted_units = RATE_UNITS[family]
        if family in ("material.conductor", "material.rod") and key == family:
            raise RateCardError(f"{key} needs a material suffix, e.g. {family}.unspecified")
        if entry.get("catalog_item_id"):
            row = catalog.get(entry["catalog_item_id"])
            if row is None:
                raise RateCardError(f"{key}: catalog item is not approved in this project")
            expires_at = row.get("expires_at")
            if isinstance(expires_at, (int, float)) and expires_at <= now_epoch_s:
                raise RateCardError(f"{key}: catalog quote has expired")
            if row.get("price_currency") != currency:
                raise RateCardError(f"{key}: catalog quote is in {row.get('price_currency')}, not {currency}; no conversion is made")
            if str(row.get("quantity_unit") or "").strip().casefold() not in accepted_units:
                raise RateCardError(f"{key}: catalog quote is per {row.get('quantity_unit')!r}, the takeoff measures {unit}")
            price = _amount(row.get("price_per_unit"))
            if price is None:
                raise RateCardError(f"{key}: catalog item has no price")
            card_rates[key] = format(price, "f")
            provenance[key] = {"source_type": "catalog", "catalog_item_id": row["id"], "catalog_version": row.get("version"),
                               "name": row.get("name"), "supplier": row.get("supplier"), "source_name": row.get("source_name"),
                               "source_url": row.get("source_url"), "quoted_at": row.get("quoted_at"),
                               "expires_at": expires_at, "unit": unit}
        else:
            price = _amount(entry.get("amount"))
            source = str(entry.get("source") or "").strip()
            if price is None:
                raise RateCardError(f"{key}: amount must be a non-negative number")
            if not source:
                raise RateCardError(f"{key}: an explicit rate needs its source")
            card_rates[key] = format(price, "f")
            provenance[key] = {"source_type": "explicit", "source": source, "unit": unit}
    assumptions: dict[str, Any] = {}
    if trench_width_m is not None:
        if not (trench_width_source or "").strip():
            raise RateCardError("trench_width_m needs its source")
        assumptions["trench_width_m"] = float(trench_width_m)
        provenance["assumption.trench_width_m"] = {"source_type": "explicit", "source": trench_width_source.strip(), "unit": "m"}
    return {"rate_card": {"currency": currency, "assumptions": assumptions, "rates": card_rates}, "provenance": provenance}


def check_rate_card_covers(rate_card: dict[str, Any], geometries: list[dict[str, Any]]) -> list[str]:
    """Lines that would stay unpriced for these geometries (the base design and the materials it uses)."""
    missing: set[str] = set()
    for geometry in geometries:
        cost = evaluate_geometry_cost(geometry, rate_card)
        missing.update(line["rate_key"] + (f" ({line['reason']})" if line.get("reason") else "")
                       for line in cost["lines"] if line["status"] == "unpriced")
    # The search adds conductors and rods even when the base has none, so their rates are always needed.
    materials = {m for g in geometries for m in takeoff(g)["conductor_length_m"]} or {gg.DEFAULT_MATERIAL}
    for material in materials:
        for family in ("material.conductor", "material.rod"):
            key = f"{family}.{material}"
            if key not in rate_card["rates"]:
                missing.add(f"{key} (missing_rate)")
    for key in FIXED_RATE_KEYS:
        if key not in rate_card["rates"]:
            missing.add(f"{key} (missing_rate)")
    if "trench_width_m" not in rate_card.get("assumptions", {}):
        missing.add("excavation.trench (missing_assumption:trench_width_m)")
    return sorted(missing)


def operator_constraints(context: dict[str, Any]) -> tuple[OperatorConstraints, dict[str, Any]]:
    """Operator limits from the resolved OP-05 context: a sourced rod-length bound narrows the default range."""
    base = OperatorConstraints()
    low, high = base.rod_length_range_m
    applied: dict[str, Any] = {"rod_length_range_m": {"min": low, "max": high, "source": "optimizer_default"}}
    bound = (context.get("variable_bounds") or {}).get("rod_length_m")
    if bound:
        low, high = max(low, float(bound["min"])), min(high, float(bound["max"]))
        if low > high:
            raise ValueError("the profile's rod length bounds leave no admissible rod")
        applied["rod_length_range_m"] = {"min": low, "max": high, "source": "constraint_profile",
                                         "provenance": (context.get("bound_provenance") or {}).get("rod_length_m")}
    return OperatorConstraints(rod_length_range_m=(low, high)), applied


def checkpoint_dir() -> Path:
    path = Path(os.getenv("OPTIMIZER_CHECKPOINT_DIR") or Path(tempfile.gettempdir()) / "spat-optimizer")
    path.mkdir(parents=True, exist_ok=True)
    return path


def complexity(geometry: dict[str, Any]) -> dict[str, Any]:
    quantities = takeoff(geometry)
    return {"conductor_length_m": quantities["conductor_length_total_m"],
            "rods": sum(r["count"] for r in quantities["rods"].values()),
            "rod_length_m": round(sum(r["length_m"] for r in quantities["rods"].values()), 6),
            "connections": quantities["connections"]}


def topology_alternatives(result: dict[str, Any], *, context: dict[str, Any], now: int) -> list[dict[str, Any]]:
    """L3 finalists that passed, cheapest first, in the shape `OptimizerRunRepository.add_alternatives` stores."""
    survivors = sorted((f for f in result.get("finalists") or [] if f.get("status") == "finalist"),
                       key=lambda f: (f["cost"], f["candidate_sha256"]))
    alternatives = []
    for rank, finalist in enumerate(survivors, start=1):
        metrics = finalist.get("metrics") or {}
        alternatives.append({
            "id": str(uuid4()), "candidate_sha256": finalist["candidate_sha256"], "rank": rank, "recommended": rank == 1,
            "candidate_snapshot": {"geometry": finalist["geometry"]},
            "evaluation_snapshot": {
                "feasible": True,               # passed the finest level; sampled, so never certified
                "feasibility_status": "UNKNOWN",
                "certified": False,
                "validated_at_level": finalist.get("level"),
                "utilization_ratio": finalist.get("ratio"),
                "metrics": metrics,
                "cost": float(finalist["cost"]),
                "cost_detail": finalist.get("cost_breakdown"),
                "geometry": finalist["geometry"],
                "complexity": complexity(finalist["geometry"]),
                "trace": {"candidate_sha256": finalist["candidate_sha256"],
                          "constraint_context_schema_version": context.get("schema_version"),
                          "problem_sha256": result.get("problem_sha256")},
            },
            "created_at": now,
        })
    return alternatives


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keep = ("schema_version", "algorithm", "seed", "starts", "max_solver_calls", "budget", "solver_calls",
            "solver_calls_total", "solver_time_units", "baseline_time_units_if_every_candidate_used_L2plus",
            "budget_exhausted", "counts", "operator_rejections", "seeds", "seeds_dropped_by_solver_check",
            "cost_currency", "evaluations_replayed", "solver_calls_spent_this_run", "problem_sha256", "certified",
            "feasibility_note")
    summary = {key: result.get(key) for key in keep}
    summary["best"] = ({k: v for k, v in result["best"].items() if k not in {"geometry", "cost_breakdown"}}
                       if result.get("best") else None)
    summary["finalists"] = [{k: v for k, v in f.items() if k not in {"geometry", "cost_breakdown"}}
                            for f in result.get("finalists") or []]
    return summary


@dataclass
class TopologyJobDeps:
    store: Any
    repository: Callable[[Any], Any]           # connection -> OptimizerRunRepository
    client_factory: Callable[[], Any]
    run_optimizer: Callable[..., dict[str, Any]]
    build_inputs: Callable[[dict[str, Any]], dict[str, Any]]   # request snapshot -> run_topology_optimizer kwargs
    evaluate_base: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None   # (inputs, client) -> L3 verdict
    clock: Callable[[], float] = time
    cancel_poll_s: float = 2.0


def execute_topology_run(deps: TopologyJobDeps, run_id: str) -> str:
    """Run one queued (or interrupted) topology run to a terminal state. Returns the final status."""
    with deps.store.transaction(write=True) as db:
        repo = deps.repository(db.connection)
        run = repo.get_run_by_id(run_id)
        if run is None:
            return "missing"
        if run["status"] not in ("queued", "running"):
            return run["status"]
        project_id = run["project_id"]
        resumed = run["status"] == "running"
        moved = repo.transition(project_id, run_id, ("queued", "running"), {
            "status": "running", "updated_at": int(deps.clock()),
            "result_summary": {"progress": {"verdicts": 0, "resumed": resumed, "started_at": int(deps.clock())}}})
        if moved is None:
            return repo.get_run(project_id, run_id)["status"]
    snapshot = run["request_snapshot"]
    checkpoint = checkpoint_dir() / f"{run_id}.json"
    last = {"poll": 0.0}

    def on_progress(progress: dict[str, Any]) -> None:
        now = deps.clock()
        if now - last["poll"] < deps.cancel_poll_s:
            return
        last["poll"] = now
        with deps.store.transaction(write=True) as db:
            repo = deps.repository(db.connection)
            if repo.transition(project_id, run_id, ("running",), {
                    "updated_at": int(now),
                    "result_summary": {"progress": {**progress, "budget": snapshot["request"]["max_solver_calls"],
                                                    "resumed": resumed}}}) is None:
                raise RunCancelled(run_id)

    try:
        inputs = deps.build_inputs(snapshot)
        client = deps.client_factory()
        result = deps.run_optimizer(**inputs, client=client, checkpoint_path=checkpoint,
                                    checkpoint_every=1, on_progress=on_progress)
        alternatives = topology_alternatives(result, context=snapshot["constraint_context"], now=int(deps.clock()))
        base = dict(snapshot.get("base") or {})
        if deps.evaluate_base is not None:
            try:
                verdict = deps.evaluate_base(inputs, client)
            except Exception as exc:   # the run's result stands; the base just stays unassessed
                verdict = {"status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:500]}
            base["electrical"] = {key: verdict.get(key) for key in ("status", "feasible", "ratio", "metrics", "level", "reason", "detail")}
        summary = {**_summary(result), "base": base, "alternatives": len(alternatives),
                   "rate_provenance": snapshot.get("rate_provenance")}
        with deps.store.transaction(write=True) as db:
            repo = deps.repository(db.connection)
            if repo.transition(project_id, run_id, ("running",), {"status": "completed", "result_summary": summary,
                                                                  "error": None, "updated_at": int(deps.clock())}) is None:
                return repo.get_run(project_id, run_id)["status"]
            repo.add_alternatives(project_id, run_id, alternatives)
        checkpoint.unlink(missing_ok=True)
        return "completed"
    except RunCancelled:
        checkpoint.unlink(missing_ok=True)
        return "cancelled"
    except Exception as exc:
        with deps.store.transaction(write=True) as db:
            deps.repository(db.connection).transition(project_id, run_id, ("running",), {
                "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:2000], "updated_at": int(deps.clock())})
        raise


def _dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["cost"] <= b["cost"] and a["utilization_ratio"] <= b["utilization_ratio"]
            and (a["cost"] < b["cost"] or a["utilization_ratio"] < b["utilization_ratio"]))


def compare_alternatives(run: dict[str, Any], alternatives: list[dict[str, Any]]) -> dict[str, Any]:
    """Side-by-side comparison (OP-13) with the cost/utilization front among the validated alternatives (OP-10)."""
    rows = []
    for alternative in alternatives:
        evaluation = alternative["evaluation_snapshot"]
        safety = evaluation.get("safety") or {}
        metrics = evaluation.get("metrics") or {"Rg_ohm": safety.get("Rg"), "Vs_v": safety.get("Vs"), "Vt_v": safety.get("Vt")}
        ratio = evaluation.get("utilization_ratio")
        geometry = evaluation.get("geometry") or (alternative.get("candidate_snapshot") or {}).get("geometry")
        rows.append({
            "alternative_id": alternative["id"], "rank": alternative.get("rank"), "recommended": alternative.get("recommended"),
            "cost": evaluation.get("cost"), "cost_by_group": (evaluation.get("cost_detail") or {}).get("by_group"),
            "Rg_ohm": metrics.get("Rg_ohm"), "Vs_v": metrics.get("Vs_v"), "Vt_v": metrics.get("Vt_v"),
            "utilization_ratio": ratio, "margin": None if ratio is None else round(1 - ratio, 6),
            "validated_at_level": evaluation.get("validated_at_level") or (evaluation.get("safety") or {}).get("FeasibilityBasis", {}).get("level"),
            "certified": evaluation.get("certified") is True,
            "complexity": evaluation.get("complexity") or (complexity(geometry) if geometry else None),
        })
    comparable = [r for r in rows if isinstance(r["cost"], (int, float)) and isinstance(r["utilization_ratio"], (int, float))]
    for row in rows:
        row["pareto"] = row in comparable and not any(_dominates(other, row) for other in comparable if other is not row)
    summary = run.get("result_summary") or {}
    base = summary.get("base")
    best = rows[0] if rows else None
    electrical = (base or {}).get("electrical") if isinstance((base or {}).get("electrical"), dict) else None
    base_complies = bool(electrical and electrical.get("feasible") is True and electrical.get("status") not in ("VIOLATED", "REJECTED", "ERROR"))
    base_violates = bool(electrical and electrical.get("status") == "VIOLATED")
    saving = None
    if best and base and isinstance(base.get("cost"), (int, float)) and base["cost"] > 0 and best["cost"] is not None:
        difference = {"amount": round(base["cost"] - best["cost"], 2), "fraction": round(1 - best["cost"] / base["cost"], 6)}
        # A saving only means something against a base that also complies; otherwise report the difference plainly.
        saving = {**difference, "kind": "saving" if base_complies else "difference",
                  "base_status": "complies" if base_complies else "violates" if base_violates else "not_assessed"}
    # Shown to the user as written, so they are in the product's language.
    warnings = ["Ninguna alternativa está certificada: pasar significa que la búsqueda muestreada no halló violaciones en el nivel más fino.",
                "El resultado es un borrador; aplicarlo crea una versión nueva del artefacto que debe aprobar un profesional competente."]
    if base and base.get("cost_status") != "complete":
        warnings.append("El costo del diseño base está incompleto; no se reporta el ahorro.")
    if base_violates:
        ratio = electrical.get("ratio")
        warnings.append("El diseño base no cumple en el nivel más fino" + (f" (utilización {ratio:.0%})" if isinstance(ratio, (int, float)) else "")
                        + "; la diferencia de costo es lo que cuesta cumplir, no un ahorro.")
    elif base and not base_complies:
        warnings.append("No se pudo evaluar si el diseño base cumple; la diferencia de costo no es un ahorro.")
    if summary.get("budget_exhausted"):
        warnings.append("Se agotó el presupuesto de llamadas al solver; uno mayor podría encontrar diseños más baratos.")
    if not rows:
        warnings.append("Ningún diseño pasó la verificación más fina dentro del presupuesto.")
    return {
        "schema_version": "spat.optimizer-comparison/1.0",
        "run_id": run["id"], "status": run["status"],
        "algorithm": (run.get("request_snapshot") or {}).get("algorithm", "discrete_local_search"),
        "currency": summary.get("cost_currency"),
        "base": base, "alternatives": rows, "saving_vs_base": saving,
        "pareto_note": "front of cost against utilization among the alternatives validated at the finest level",
        "inputs": {key: (run.get("request_snapshot") or {}).get("request", {}).get(key)
                   for key in ("soil", "injection_a", "exposure", "standards", "seed", "max_solver_calls")},
        "constraint_profile": ((run.get("request_snapshot") or {}).get("constraint_context") or {}).get("selected_profiles"),
        "rate_provenance": (run.get("request_snapshot") or {}).get("rate_provenance"),
        "warnings": warnings,
    }
