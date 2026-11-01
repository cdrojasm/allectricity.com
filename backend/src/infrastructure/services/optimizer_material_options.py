"""Adapt approved, versioned catalog entries into OP-05 discrete domains."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from time import time
from typing import Any


def approved_material_domains(rows: list[dict[str, Any]], *, now_epoch_s: int) -> list[dict[str, Any]]:
    """Build ``resolve_discrete_domains`` inputs from approved catalog snapshots.

    Unapproved/archived rows are omitted. Expired approved quotes remain visible
    only as blocked options, preserving their pinned item version and provenance.
    No quantity or currency conversion, or free-text engineering inference, occurs.
    """
    groups: dict[str, dict[str, Any]] = {}
    conflicted_domains: set[str] = set()
    for row in rows:
        if row.get("status") != "approved":
            continue
        item_id = row.get("id")
        version = row.get("version")
        if not isinstance(item_id, str) or not item_id.strip() or not isinstance(version, int):
            continue
        quote_source = {
            "catalog_item_id": item_id,
            "catalog_version": version,
            "quote": {
                "unit_price": str(row.get("price_per_unit")) if row.get("price_per_unit") is not None else None,
                "currency": row.get("price_currency"),
                "price_unit": row.get("quantity_unit"),
                "supplier": row.get("supplier"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "quoted_at": row.get("quoted_at"),
                "expires_at": row.get("expires_at"),
            },
        }
        expires_at = row.get("expires_at")
        expired = isinstance(expires_at, (int, float)) and expires_at <= now_epoch_s
        quote_cost_ready = (row.get("price_per_unit") is not None and row.get("price_currency")
                            and row.get("quantity_unit"))
        structured = row.get("structured_options")
        if not isinstance(structured, dict):
            continue
        domain_id = structured.get("domain_id")
        options = structured.get("options")
        if not isinstance(domain_id, str) or not domain_id.strip() or not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            target, unit = option.get("target"), option.get("unit")
            value, source = option.get("value"), option.get("provenance")
            option_key = option.get("option_id")
            if (not isinstance(target, str) or not target.strip() or not isinstance(unit, str)
                    or not unit.strip() or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isinstance(option_key, str) or not option_key.strip()
                    or not isinstance(source, dict) or not source):
                continue
            group = groups.setdefault(domain_id, {
                "domain_id": domain_id,
                "target": target,
                "unit": unit,
                "status": "active",
                "provenance": {"source_type": "approved_project_material_catalog", "domain_id": domain_id},
                "options": [],
            })
            # Domain IDs are the identity boundary. Conflicting engineering meaning
            # under one ID is rejected instead of merged into a misleading domain.
            if group["target"] != target or group["unit"] != unit:
                conflicted_domains.add(domain_id)
                continue
            provenance = {**source, **quote_source, "product_name": row.get("name"),
                          "category": row.get("category"), "material": row.get("material"),
                          "specification": row.get("specification")}
            group["options"].append({
                "option_id": f"{item_id}@v{version}:{option_key}",
                "value": value,
                "status": "available" if quote_cost_ready and not expired else "blocked",
                "applicability_filters": option.get("applicability_filters") or {},
                "provenance": provenance,
            })

    for domain in groups.values():
        domain["options"].sort(key=lambda option: option["option_id"])
        if domain["domain_id"] in conflicted_domains:
            domain["status"] = "blocked"
            for option in domain["options"]:
                option["status"] = "blocked"
    return [groups[key] for key in sorted(groups)]


def evaluate_material_cost(
    selected_options: list[dict[str, Any]],
    explicit_quantities: dict[str, dict[str, Any]],
    *,
    now_epoch_s: int | None = None,
) -> dict[str, Any]:
    """Price selected options from explicit quantities; never infer or convert."""
    if not isinstance(selected_options, list) or not isinstance(explicit_quantities, dict):
        raise ValueError("selected_options and explicit_quantities must be a list and object")
    lines: list[dict[str, Any]] = []
    totals: dict[str, Decimal] = defaultdict(Decimal)
    warnings: list[str] = []
    seen: set[str] = set()
    evaluation_time = int(time()) if now_epoch_s is None else now_epoch_s
    for index, option in enumerate(selected_options):
        if not isinstance(option, dict):
            raise ValueError(f"selected_options[{index}] must be an object")
        option_id = option.get("option_id")
        if not isinstance(option_id, str) or not option_id.strip():
            raise ValueError(f"selected_options[{index}].option_id must be nonempty")
        if option_id in seen:
            raise ValueError(f"duplicate selected option {option_id!r}")
        seen.add(option_id)
        provenance = option.get("provenance")
        quote = provenance.get("quote") if isinstance(provenance, dict) else None
        if not isinstance(quote, dict):
            reason = "missing_quote"
        else:
            currency, price_unit = quote.get("currency"), quote.get("price_unit")
            expires_at = quote.get("expires_at")
            try:
                unit_price = Decimal(str(quote.get("unit_price")))
            except (InvalidOperation, TypeError, ValueError):
                unit_price = Decimal("NaN")
            quantity_record = explicit_quantities.get(option_id)
            if (not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha()
                    or currency.upper() != currency):
                reason = "invalid_currency"
            elif isinstance(expires_at, (int, float, Decimal)) and expires_at <= evaluation_time:
                reason = "expired_quote"
            elif not unit_price.is_finite() or unit_price < 0:
                reason = "invalid_unit_price"
            elif not isinstance(price_unit, str) or not price_unit.strip():
                reason = "missing_price_unit"
            elif not isinstance(quantity_record, dict):
                reason = "missing_explicit_quantity"
            elif quantity_record.get("unit") != price_unit:
                reason = "quantity_unit_mismatch"
            else:
                quantity = quantity_record.get("value")
                try:
                    decimal_quantity = Decimal(str(quantity))
                except (InvalidOperation, TypeError, ValueError):
                    decimal_quantity = Decimal("NaN")
                if (isinstance(quantity, bool) or not isinstance(quantity, (int, float, Decimal))
                        or not decimal_quantity.is_finite() or decimal_quantity < 0):
                    reason = "invalid_quantity"
                else:
                    amount = unit_price * decimal_quantity
                    totals[currency] += amount
                    lines.append({
                        "option_id": option_id,
                        "catalog_item_id": provenance.get("catalog_item_id"),
                        "catalog_version": provenance.get("catalog_version"),
                        "status": "priced",
                        "quantity": str(quantity),
                        "quantity_unit": price_unit,
                        "unit_price": str(unit_price),
                        "currency": currency,
                        "amount": format(amount, "f"),
                        "quote_source": {key: quote.get(key) for key in (
                            "supplier", "source_name", "source_url", "quoted_at", "expires_at"
                        )},
                    })
                    continue
        warnings.append(f"{option_id}: {reason}")
        lines.append({"option_id": option_id, "status": "unpriced", "reason": reason})
    warnings.extend(
        f"{option_id}: quantity supplied for an unselected option"
        for option_id in sorted(set(explicit_quantities) - seen)
    )
    return {
        "status": "complete" if not warnings else "incomplete",
        "lines": lines,
        "currency_totals": [
            {"currency": currency, "amount": format(amount, "f")}
            for currency, amount in sorted(totals.items())
        ],
        "warnings": warnings,
        "currency_conversion": "none",
    }
