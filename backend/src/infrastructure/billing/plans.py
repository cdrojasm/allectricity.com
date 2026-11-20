"""Subscription tiers, configured only through environment variables (aligned comma-separated lists):

    MP_PLAN_NAMES=ultimate,standard,essentials
    MP_PLAN_IDS=<preapproval_plan_id>,<...>,<...>          (MP_TEST_PLAN_IDS / MP_PROD_PLAN_IDS override per mode)
    MP_PLAN_PRICES_USD=199,49,19
    MP_PLAN_MONTHLY_TOKENS=30000000,8000000,3000000
    MP_MODE=test|prod   (credentials used to charge: MP_<MODE>_ACCESS_TOKEN, MP_<MODE>_PUBLIC_KEY)

Tiers are ranked by price, so an upgrade is any tier with a higher price. The price actually charged (COP) is
read from the Mercado Pago plan; the USD price is only a reference shown next to it.
"""

import logging
import os
import re
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from src.infrastructure.billing import mercadopago

logger = logging.getLogger(__name__)
_cache: dict = {}
_lock = Lock()
DETAILS_TTL_SECONDS = 600


class PlanConfigError(ValueError):
    """MP_PLAN_* lists are missing, misaligned or malformed."""


@dataclass(frozen=True)
class Plan:
    name: str
    plan_id: str
    price_usd: float
    monthly_tokens: int
    rank: int  # 0 = cheapest


def _items(variable: str) -> list[str]:
    raw = os.getenv(variable, "").strip().strip("\"'")
    return [item.strip() for item in raw.split(",")] if raw else []


def configured() -> list[Plan]:
    # Plans live in the account that owns the credentials: the test seller cannot see the production plans, so
    # test mode may point at its own copies (MP_TEST_PLAN_IDS, created by scripts/create_mp_test_plans.py).
    names = _items("MP_PLAN_NAMES")
    ids = _items(f"MP_{mode().upper()}_PLAN_IDS") or _items("MP_PLAN_IDS")
    prices, tokens = _items("MP_PLAN_PRICES_USD"), _items("MP_PLAN_MONTHLY_TOKENS")
    if not any((names, ids, prices, tokens)):
        return []
    if not (len(names) == len(ids) == len(prices) == len(tokens)) or not names:
        raise PlanConfigError("MP_PLAN_NAMES, MP_PLAN_IDS, MP_PLAN_PRICES_USD y MP_PLAN_MONTHLY_TOKENS deben tener "
                              "el mismo número de elementos, en el mismo orden")
    if len(set(names)) != len(names) or any(not re.fullmatch(r"[a-z0-9_-]{1,40}", name) for name in names):
        raise PlanConfigError("MP_PLAN_NAMES: nombres únicos en minúscula, sin espacios")
    if any(not re.fullmatch(r"[0-9a-f]{32}", plan_id) for plan_id in ids):
        raise PlanConfigError("MP_PLAN_IDS: cada elemento debe ser un preapproval_plan_id (32 caracteres hex)")
    try:
        parsed = [(name, plan_id, float(price), int(token))
                  for name, plan_id, price, token in zip(names, ids, prices, tokens)]
    except ValueError as exc:
        raise PlanConfigError("MP_PLAN_PRICES_USD y MP_PLAN_MONTHLY_TOKENS deben ser números sin símbolos") from exc
    if any(price <= 0 or token <= 0 for _, _, price, token in parsed):
        raise PlanConfigError("Precios y tokens deben ser positivos")
    ordered = sorted(parsed, key=lambda item: item[2])
    return [Plan(name, plan_id, price, token, rank) for rank, (name, plan_id, price, token) in enumerate(ordered)]


def get(name: str) -> Plan | None:
    return next((plan for plan in configured() if plan.name == name), None)


def mode() -> str:
    value = os.getenv("MP_MODE", "test").strip().lower()
    return value if value in mercadopago.MODES else "test"


def public_key(current_mode: str | None = None) -> str:
    return os.getenv(f"MP_{(current_mode or mode()).upper()}_PUBLIC_KEY", "").strip()


def details(plan: Plan, current_mode: str | None = None) -> dict:
    """Amount and currency charged by the Mercado Pago plan (cached); `available` is False when it cannot be sold."""
    current_mode = current_mode or mode()
    key = (current_mode, plan.plan_id)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            return cached[1]
    try:
        status, resource = mercadopago.fetch_resource(current_mode, "subscription_preapproval_plan", plan.plan_id)
    except (LookupError, mercadopago.ResourceUnavailable) as exc:
        return {"available": False, "reason": str(exc)}
    if status != 200 or not isinstance(resource, dict):
        return {"available": False, "reason": f"Mercado Pago no devolvió el plan ({status})"}
    recurring = resource.get("auto_recurring") or {}
    reference = str(resource.get("external_reference") or "").strip()
    info = {
        "available": resource.get("status") in (None, "active") and not (reference and reference != plan.name),
        "amount": recurring.get("transaction_amount"),
        "currency": recurring.get("currency_id"),
        "frequency": recurring.get("frequency"),
        "frequency_type": recurring.get("frequency_type"),
        "reason": resource.get("reason"),
    }
    if reference and reference != plan.name:
        info["unavailable_reason"] = (f"El código de referencia del plan en Mercado Pago es «{reference}» y no "
                                      f"coincide con «{plan.name}»: revisa el orden de MP_PLAN_*")
        logger.error(info["unavailable_reason"])
    with _lock:
        _cache[key] = (monotonic() + DETAILS_TTL_SECONDS, info)
    return info
