"""Deterministic local search over finite, sourced optimizer domains (OP-06).

This module owns only candidate generation and search orchestration. Geometry
construction, electrical evaluation, and cost accounting remain explicit caller
callbacks so the search cannot invent engineering rules or prices.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import random
from math import isfinite
from typing import Any, Callable

from src.domain.spat.feasibility import admits


@dataclass(frozen=True)
class SearchOption:
    value: Any
    option_id: str | None = None


BuildCandidate = Callable[[dict[str, Any]], Any]
EvaluateSafety = Callable[[Any, dict[str, Any]], dict[str, Any]]
EvaluateCost = Callable[[Any, Any, dict[str, Any]], float | dict[str, Any]]


def _canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate parameters must be JSON-serializable finite values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _path_set(target: dict[str, Any], path: str, value: Any) -> None:
    """Assign a dotted/indexed parameter path (e.g. rod_lengths_m[0])."""
    if not isinstance(path, str) or not path:
        raise ValueError("search variable paths must be nonempty strings")
    tokens: list[str | int] = []
    token = ""
    i = 0
    while i < len(path):
        if path[i] == ".":
            if not token:
                raise ValueError(f"invalid variable path {path!r}")
            tokens.append(token)
            token = ""
            i += 1
        elif path[i] == "[":
            if token:
                tokens.append(token)
                token = ""
            end = path.find("]", i + 1)
            if end < 0 or not path[i + 1:end].isdigit():
                raise ValueError(f"invalid variable path {path!r}")
            tokens.append(int(path[i + 1:end]))
            i = end + 1
        else:
            token += path[i]
            i += 1
    if token:
        tokens.append(token)
    if not tokens or isinstance(tokens[0], int):
        raise ValueError(f"invalid variable path {path!r}")
    current: Any = target
    for item in tokens[:-1]:
        if isinstance(item, str):
            if not isinstance(current, dict) or item not in current:
                raise ValueError(f"variable path {path!r} is absent from base parameters")
            current = current[item]
        else:
            if not isinstance(current, list) or item >= len(current):
                raise ValueError(f"variable path {path!r} is absent from base parameters")
            current = current[item]
    leaf = tokens[-1]
    if isinstance(leaf, str):
        if not isinstance(current, dict) or leaf not in current:
            raise ValueError(f"variable path {path!r} is absent from base parameters")
        current[leaf] = deepcopy(value)
    else:
        if not isinstance(current, list) or leaf >= len(current):
            raise ValueError(f"variable path {path!r} is absent from base parameters")
        current[leaf] = deepcopy(value)


def _normalize_domains(
    domains: dict[str, list[Any] | dict[str, Any]],
    bounds: dict[str, dict[str, float]] | None,
) -> dict[str, list[SearchOption]]:
    normalized: dict[str, list[SearchOption]] = {}
    for path, raw in domains.items():
        if isinstance(raw, dict):
            if raw.get("status") != "ready" or not raw.get("candidate_values"):
                raise ValueError(f"discrete domain for {path!r} is not ready")
            candidate_ids = set(raw.get("candidate_option_ids", []))
            options_by_id = {item.get("option_id"): item for item in raw.get("options", [])
                             if item.get("option_id") in candidate_ids}
            # Keep every approved option identity, including distinct products with
            # the same engineering value. Cost and provenance can differ by option.
            options = [SearchOption(float(item["value"]), option_id)
                       for option_id, item in options_by_id.items()
                       if item.get("value") in raw["candidate_values"]]
            represented_values = {option.value for option in options}
            options.extend(SearchOption(float(value)) for value in raw["candidate_values"]
                           if float(value) not in represented_values)
        elif isinstance(raw, list):
            options = [item if isinstance(item, SearchOption) else SearchOption(item)
                       for item in raw]
        else:
            raise ValueError(f"domain for {path!r} must be a list or resolved discrete-domain record")
        if not options:
            raise ValueError(f"domain for {path!r} must not be empty")
        if any(isinstance(option.value, bool) or not isinstance(option.value, (int, float))
               or not isfinite(option.value) for option in options):
            raise ValueError(f"domain values for {path!r} must be finite numbers")
        bound = (bounds or {}).get(path)
        if bound is not None:
            if set(bound) != {"min", "max"}:
                raise ValueError(f"bounds for {path!r} must contain min and max")
            low, high = bound["min"], bound["max"]
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x)
                   for x in (low, high)) or low > high:
                raise ValueError(f"bounds for {path!r} must be finite and ordered")
            options = [option for option in options if isinstance(option.value, (int, float))
                       and not isinstance(option.value, bool) and low <= option.value <= high]
        # Stable unique values; option identity is retained when available.
        unique: dict[tuple[str, str | None], SearchOption] = {}
        for option in options:
            key = (_canonical_hash(option.value), option.option_id)
            unique[key] = option
        if not unique:
            raise ValueError(f"domain for {path!r} has no values within its resolved bounds")
        normalized[path] = sorted(unique.values(), key=lambda option: (
            float(option.value) if isinstance(option.value, (int, float)) else repr(option.value),
            option.option_id or ""))
    if not normalized:
        raise ValueError("at least one finite discrete domain is required")
    return normalized


def search_discrete_local(
    *,
    base_parameters: dict[str, Any],
    domains: dict[str, list[Any] | dict[str, Any]],
    build_candidate: BuildCandidate,
    evaluate_safety: EvaluateSafety,
    evaluate_cost: EvaluateCost,
    seed: int,
    max_evaluations: int,
    restarts: int = 5,
    bounds: dict[str, dict[str, float]] | None = None,
    start: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run deterministic best-improvement local search on discrete domains.

    The budget counts unique candidates passed to the builder, including candidates
    rejected as unbuildable or unsafe. A candidate is eligible for the incumbent only
    when construction succeeds and safety reports ``Feasible is True``. Missing,
    false, or unknown feasibility is rejected. The cost callback runs only for eligible
    candidates. Cached candidate hashes are never charged or evaluated twice.

    Neighbor moves change one variable by one position in its sorted domain. Each
    restart begins at a seeded random combination and follows strict cost improvements.
    With ``start`` (a value for every optimized variable) the first restart begins at the
    domain option nearest to it instead, which makes the search a local refinement of a
    design already known; later restarts remain random.
    """
    if not isinstance(base_parameters, dict):
        raise ValueError("base_parameters must be an object")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    for name, value in (("max_evaluations", max_evaluations), ("restarts", restarts)):
        if isinstance(value, bool) or not isinstance(value, int) or value < (1 if name == "max_evaluations" else 0):
            raise ValueError(f"{name} must be a {'positive' if name == 'max_evaluations' else 'nonnegative'} integer")
    variables = _normalize_domains(domains, bounds)
    start_indices: dict[str, int] | None = None
    if start is not None:
        if set(start) != set(variables):
            raise ValueError("start must give a value for every optimized variable")
        start_indices = {path: min(range(len(options)), key=lambda i: (abs(float(options[i].value) - float(start[path])), i))
                         for path, options in variables.items()}
    rng = random.Random(seed)
    cache: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    unique_evaluations = 0
    incumbent: dict[str, Any] | None = None
    exhausted = False

    def make_candidate(indices: dict[str, int]) -> dict[str, Any]:
        params = deepcopy(base_parameters)
        selected: dict[str, str] = {}
        for path, options in variables.items():
            option = options[indices[path]]
            _path_set(params, path, option.value)
            if option.option_id is not None:
                selected[path] = option.option_id
        params["selected_discrete_options"] = selected
        return params

    def evaluate(indices: dict[str, int]) -> tuple[dict[str, Any] | None, bool]:
        nonlocal unique_evaluations, exhausted, incumbent
        params = make_candidate(indices)
        candidate_hash = _canonical_hash(params)
        if candidate_hash in cache:
            return cache[candidate_hash], True
        if unique_evaluations >= max_evaluations:
            exhausted = True
            return None, False
        unique_evaluations += 1
        record: dict[str, Any] = {"candidate_sha256": candidate_hash,
                                  "parameters": params, "status": "rejected"}
        try:
            built = build_candidate(deepcopy(params))
        except Exception as exc:  # callback boundary; preserve failure as a trace record
            record.update(reason="construction_error", detail=str(exc))
            cache[candidate_hash] = record
            diagnostics.append({key: value for key, value in record.items() if key != "parameters"})
            return record, False
        if built is None or (isinstance(built, dict) and built.get("constructible") is False):
            record.update(reason="not_constructible")
            cache[candidate_hash] = record
            diagnostics.append({key: value for key, value in record.items() if key != "parameters"})
            return record, False
        try:
            safety = evaluate_safety(built, deepcopy(params))
        except Exception as exc:
            record.update(reason="safety_evaluation_error", detail=str(exc))
            cache[candidate_hash] = record
            diagnostics.append({key: value for key, value in record.items() if key != "parameters"})
            return record, False
        if not isinstance(safety, dict) or not admits(
                level="L2", status=safety.get("FeasibilityStatus"), feasible=safety.get("Feasible")):
            record.update(reason="safety_not_feasible", safety=safety)
            cache[candidate_hash] = record
            diagnostics.append({key: value for key, value in record.items() if key != "parameters"})
            return record, False
        try:
            cost_result = evaluate_cost(built, safety, deepcopy(params))
            if isinstance(cost_result, dict):
                cost_detail = cost_result
                if cost_result.get("status") == "incomplete":
                    raise ValueError("cost result is incomplete")
                currency_totals = cost_result.get("currency_totals")
                if currency_totals is not None:
                    if len(currency_totals) != 1:
                        raise ValueError("cost comparison requires exactly one currency; conversion policy is not configured")
                    total = currency_totals[0]
                    if not isinstance(total, dict) or not isinstance(total.get("amount"), str):
                        raise ValueError("currency total must include a decimal amount")
                    try:
                        cost = float(total["amount"])
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise ValueError("currency total must be a finite amount") from exc
                    cost_detail = {**cost_result, "objective_currency": total.get("currency")}
                else:
                    cost = cost_result.get("total")
            else:
                cost = cost_result
                cost_detail = {"total": cost}
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not isfinite(cost):
                raise ValueError("cost callback must return a finite number or an object with finite total")
        except Exception as exc:
            record.update(reason="cost_evaluation_error", detail=str(exc), safety=safety)
            cache[candidate_hash] = record
            diagnostics.append({key: value for key, value in record.items() if key != "parameters"})
            return record, False
        record.update(status="feasible", safety=safety, cost=float(cost), cost_detail=cost_detail)
        cache[candidate_hash] = record
        if incumbent is None or record["cost"] < incumbent["cost"]:
            incumbent = record
        return record, False

    restart_summaries = []
    attempts = max(1, restarts)
    for restart in range(attempts):
        if restart == 0 and start_indices is not None:
            indices = dict(start_indices)
        else:
            indices = {path: rng.randrange(len(options)) for path, options in variables.items()}
        current, _ = evaluate(indices)
        if exhausted:
            break
        while True:
            current_cost = current["cost"] if current and current.get("status") == "feasible" else float("inf")
            neighbors: list[tuple[float, str, dict[str, int], dict[str, Any]]] = []
            for path, options in variables.items():
                for offset in (-1, 1):
                    next_index = indices[path] + offset
                    if not 0 <= next_index < len(options):
                        continue
                    candidate_indices = dict(indices)
                    candidate_indices[path] = next_index
                    candidate_params = make_candidate(candidate_indices)
                    candidate_hash = _canonical_hash(candidate_params)
                    if candidate_hash in cache:
                        evaluated = cache[candidate_hash]
                    else:
                        evaluated, _ = evaluate(candidate_indices)
                    if exhausted:
                        break
                    if evaluated and evaluated.get("status") == "feasible" and evaluated["cost"] < current_cost:
                        neighbors.append((evaluated["cost"], candidate_hash, candidate_indices, evaluated))
                if exhausted:
                    break
            if exhausted or not neighbors:
                break
            _, _, indices, current = min(neighbors, key=lambda item: (item[0], item[1]))
        restart_summaries.append({"restart": restart, "terminal_candidate_sha256":
                                  current.get("candidate_sha256") if current else None,
                                  "terminal_status": current.get("status") if current else "not_evaluated"})
        if exhausted:
            break

    return {
        "schema_version": "spat.optimizer-search/1.0",
        "algorithm": "discrete_best_improvement_local_search",
        "seed": seed,
        "max_evaluations": max_evaluations,
        "unique_evaluations": unique_evaluations,
        "cache_entries": len(cache),
        "budget_exhausted": exhausted,
        "restarts_requested": restarts,
        "restarts_started": len(restart_summaries),
        "restart_summaries": restart_summaries,
        "best": deepcopy(incumbent),
        "feasible_candidates": sorted(
            (deepcopy(record) for record in cache.values() if record.get("status") == "feasible"),
            key=lambda record: (record["cost"], record["candidate_sha256"]),
        ),
        "diagnostics": diagnostics,
    }
