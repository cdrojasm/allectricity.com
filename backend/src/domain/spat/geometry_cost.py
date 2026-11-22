"""Cost of a grounding geometry without touching the electrical solver (OPT-006).

Two steps, both pure functions of the geometry and an explicit rate card:

  takeoff(graph)   quantities read off the normalized network: conductor length by material,
                   rods by material (count and length), connections, trench length and volume.
  price(...)       multiplies each quantity by a rate the caller supplied, in materials, excavation
                   and installation groups, using Decimal so the same input always prints the same
                   amount.

Nothing is inferred: a rate or assumption that is missing leaves its line `unpriced` and the cost
`incomplete`, like the catalog pricing in `optimizer_material_options`. The result also carries
`currency_totals` in the same shape, so it can serve as the search's `evaluate_cost`. It reports
`solver_evaluations_used: 0`; it never touches the evaluation budget.

Rate card (all prices are strings or numbers in one currency):
    {"currency": "COP",
     "assumptions": {"trench_width_m": 0.4},
     "rates": {"material.conductor.<material>": price per m,
               "material.rod.<material>": price per m of rod,
               "excavation.trench": price per m3,
               "installation.conductor": price per m,
               "installation.rod": price per rod,
               "installation.connection": price per connection}}
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from src.domain.spat.geometry_graph import GeometryGraph, from_geometry, normalize, _dist

GROUPS = ("materials", "excavation", "installation")


def takeoff(source: GeometryGraph | dict, *, trench_width_m: float | None = None) -> dict[str, Any]:
    """Quantities of the normalized network. Excavation volume needs an explicit trench width."""
    graph = normalize(source if isinstance(source, GeometryGraph) else from_geometry(source))
    conductor_by_material: dict[str, float] = {}
    for a, b, material in graph.segments:
        conductor_by_material[material] = conductor_by_material.get(material, 0.0) + _dist(a, b)
    rods_by_material: dict[str, dict[str, float]] = {}
    for _, length, material in graph.rods:
        entry = rods_by_material.setdefault(material, {"count": 0, "length_m": 0.0})
        entry["count"] += 1
        entry["length_m"] += length
    degree = graph.degree()
    # A connection is a place where conductors are joined to each other or to a rod.
    conductor_joints = sum(1 for node, d in degree.items() if d >= 3)   # crossings and T junctions between conductors
    rod_joints = len(graph.rods)                                          # each rod is bonded to the grid once
    connections = conductor_joints + rod_joints
    conductor_length = sum(conductor_by_material.values())
    burial = graph.site.burial_depth_m
    return {
        "conductor_length_m": {m: round(v, 6) for m, v in sorted(conductor_by_material.items())},
        "conductor_length_total_m": round(conductor_length, 6),
        "rods": {m: {"count": int(v["count"]), "length_m": round(v["length_m"], 6)} for m, v in sorted(rods_by_material.items())},
        "connections": connections,
        "connections_by_type": {"conductor_conductor": conductor_joints, "conductor_rod": rod_joints},
        "trench_length_m": round(conductor_length, 6),
        "burial_depth_m": burial,
        "excavation_m3": None if trench_width_m is None else round(conductor_length * trench_width_m * burial, 6),
        "trench_width_m": trench_width_m,
    }


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def price(quantities: dict[str, Any], rate_card: dict[str, Any]) -> dict[str, Any]:
    """Itemised cost by group from a takeoff and a rate card; unpriced lines make it incomplete."""
    currency = rate_card.get("currency")
    if not (isinstance(currency, str) and len(currency) == 3 and currency.isalpha() and currency.upper() == currency):
        raise ValueError("rate card currency must be an uppercase three-letter code")
    rates = rate_card.get("rates") or {}
    lines: list[dict[str, Any]] = []
    totals = {group: Decimal(0) for group in GROUPS}
    warnings: list[str] = []

    def add(group: str, key: str, label: str, quantity: Any, unit: str) -> None:
        rate = _decimal(rates.get(key))
        amount_quantity = _decimal(quantity)
        if amount_quantity is None:
            lines.append({"group": group, "item": label, "rate_key": key, "status": "unpriced", "reason": "missing_quantity"})
            warnings.append(f"{label}: missing_quantity")
        elif amount_quantity == 0:
            return    # nothing of this item in the design; a missing rate for it does not matter
        elif rate is None:
            lines.append({"group": group, "item": label, "rate_key": key, "status": "unpriced", "reason": "missing_rate",
                          "quantity": str(amount_quantity), "unit": unit})
            warnings.append(f"{label}: missing_rate")
        else:
            amount = rate * amount_quantity
            totals[group] += amount
            lines.append({"group": group, "item": label, "rate_key": key, "status": "priced", "quantity": str(amount_quantity),
                          "unit": unit, "unit_price": str(rate), "currency": currency, "amount": format(amount, "f")})

    for material, length in quantities["conductor_length_m"].items():
        add("materials", f"material.conductor.{material}", f"conductor ({material})", length, "m")
    for material, rods in quantities["rods"].items():
        add("materials", f"material.rod.{material}", f"rod ({material})", rods["length_m"], "m")
    if quantities["excavation_m3"] is None and quantities["trench_length_m"]:
        lines.append({"group": "excavation", "item": "trench", "rate_key": "excavation.trench", "status": "unpriced",
                      "reason": "missing_assumption:trench_width_m"})
        warnings.append("trench: missing_assumption:trench_width_m")
    else:
        add("excavation", "excavation.trench", "trench", quantities["excavation_m3"] or 0, "m3")
    add("installation", "installation.conductor", "conductor laying", quantities["conductor_length_total_m"], "m")
    add("installation", "installation.rod", "rod driving", sum(r["count"] for r in quantities["rods"].values()), "rod")
    add("installation", "installation.connection", "connections", quantities["connections"], "connection")

    total = sum(totals.values(), Decimal(0))
    return {
        "status": "complete" if not warnings else "incomplete",
        "currency": currency,
        "by_group": {group: format(totals[group], "f") for group in GROUPS},
        "total": format(total, "f"),
        "currency_totals": [{"currency": currency, "amount": format(total, "f")}],
        "lines": lines,
        "warnings": warnings,
        "currency_conversion": "none",
    }


def evaluate_geometry_cost(source: GeometryGraph | dict, rate_card: dict[str, Any]) -> dict[str, Any]:
    """Itemised, reproducible cost of a geometry. Valid or not, it never calls the solver."""
    graph = normalize(source if isinstance(source, GeometryGraph) else from_geometry(source))
    quantities = takeoff(graph, trench_width_m=(rate_card.get("assumptions") or {}).get("trench_width_m"))
    result = price(quantities, rate_card)
    result["takeoff"] = quantities
    result["solver_evaluations_used"] = 0
    result["input_sha256"] = hashlib.sha256(json.dumps(
        {"quantities": quantities, "rate_card": rate_card}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return result
