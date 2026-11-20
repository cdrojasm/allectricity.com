"""Tiers: who has which plan, paid through Mercado Pago or granted by a license code.

A subscription owns one token budget with the same id. Rules:
- Checkout is asynchronous: the API stores a `pending` subscription and the billing worker creates the Mercado
  Pago preapproval with the card token. Authorized → the budget is loaded with the tier's monthly tokens.
- Each approved monthly charge resets the budget (unused tokens are lost), at most once per MP_RESET_MIN_DAYS
  (default 20) so the first charge, which arrives right after activation, does not reset it twice.
- Upgrade only (a higher-priced tier). The previous subscription is cancelled once the new one is authorized;
  the new tier's full budget replaces the old one.
- Failed charge → `past_due` for MP_GRACE_DAYS (default 7), then `suspended` (agent blocked, data kept). An
  approved retry reactivates it.
- Cancelled from Mercado Pago → access until the end of the paid period, then `expired`.
- Licenses: one code per person, single use. The code grants the tier for N months, recharged monthly.
"""

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime
from time import time

from src.application.use_cases.identity import audit, uid
from src.domain.identity import ServiceError
from src.infrastructure.billing import mercadopago, plans

logger = logging.getLogger(__name__)
TABLE = "billing_subscriptions"
LICENSES = "billing_licenses"
DAY = 86400
PERIOD = 30 * DAY
PENDING_TIMEOUT = 30 * 60
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
REMOTE_CANCEL_PENDING = "remote_cancel_pending"


def _now() -> int:
    return int(time())


def grace_seconds() -> int:
    return int(os.getenv("MP_GRACE_DAYS", "7")) * DAY


def reset_min_seconds() -> int:
    return int(os.getenv("MP_RESET_MIN_DAYS", "20")) * DAY


def has_access(subscription: dict, at: int) -> bool:
    if subscription["status"] in ("authorized", "past_due"):
        return True
    return subscription["status"] == "cancelled" and (subscription.get("ends_at") or 0) > at


def _rank(tier: str) -> int:
    plan = plans.get(tier)
    return plan.rank if plan else -1


def current(db, user_id: str, at: int | None = None) -> dict | None:
    """The subscription that gives the user access now (the highest tier if several overlap)."""
    at = at or _now()
    active = [row for row in db.many(TABLE, user_id=user_id, limit=None) if has_access(row, at)]
    return max(active, key=lambda row: (_rank(row["tier"]), row["created_at"])) if active else None


def _grant(db, subscription: dict, at: int) -> None:
    """Load (or reset) the subscription's budget with its tier's monthly tokens."""
    plan = plans.get(subscription["tier"])
    if plan is None:
        logger.error("Tier %s is no longer configured; budget of %s left unchanged", subscription["tier"],
                     subscription["id"])
        return
    name = f"Plan {subscription['tier']}"
    if db.one("budget", id=subscription["id"]):
        db.change("budget", subscription["id"], name=name, total_tokens=plan.monthly_tokens, used_tokens=0,
                  active=True)
    else:
        db.add("budget", id=subscription["id"], user_id=subscription["user_id"], name=name,
               total_tokens=plan.monthly_tokens, used_tokens=0, active=True, created_at=at)


def _set_budget_active(db, subscription_id: str, active: bool) -> None:
    if db.one("budget", id=subscription_id):
        db.change("budget", subscription_id, active=active)


def _parse_time(value) -> int | None:
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()) if value else None
    except ValueError:
        return None


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def code_hash(code: str) -> str:
    return hashlib.sha256(f"terra-license:{normalize_code(code)}".encode()).hexdigest()


def new_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))  # 60 bits
    return "TERRA-" + "-".join(body[i:i + 4] for i in range(0, 12, 4))


def public_url(path: str) -> str:
    base = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/") or "https://localhost"
    return base + path


class Subscriptions:
    def __init__(self, store, http_client=None):
        self.store, self.http_client = store, http_client

    # Read model --------------------------------------------------------------------------------------
    def _view(self, db, row: dict | None) -> dict | None:
        if row is None:
            return None
        budget = db.one("budget", id=row["id"])
        return {key: row.get(key) for key in ("id", "tier", "provider", "status", "period_end", "grace_until",
                                              "ends_at", "error", "created_at")} | {
            "tokens": {"total": budget["total_tokens"], "used": budget["used_tokens"]} if budget else None}

    def summary(self, user_id: str) -> dict:
        at = _now()
        with self.store.transaction() as db:
            active = current(db, user_id, at)
            rows = sorted(db.many(TABLE, user_id=user_id, provider="mercadopago", limit=None),
                          key=lambda row: row["created_at"], reverse=True)
            latest = rows[0] if rows else None
            # The latest checkout while it runs, or its failure for a day (so the user sees why it did not go through).
            recent = latest and (latest["status"] == "pending"
                                 or (latest["status"] == "failed" and at - latest["updated_at"] < DAY))
            checkout = latest if recent and (active is None or latest["created_at"] > active["created_at"]) else None
            return {"subscription": self._view(db, active), "checkout": self._view(db, checkout)}

    # Checkout ----------------------------------------------------------------------------------------
    def start_checkout(self, user_id: str, tier: str) -> dict:
        plan = plans.get(tier)
        if plan is None:
            raise ServiceError(404, "Plan no encontrado")
        at = _now()
        with self.store.transaction(write=True) as db:
            active = current(db, user_id, at)
            if active and _rank(active["tier"]) >= plan.rank:
                raise ServiceError(409, f"Ya tienes el plan {active['tier']}: solo puedes cambiar a un plan superior.")
            if any(at - row["created_at"] < PENDING_TIMEOUT
                   for row in db.many(TABLE, user_id=user_id, status="pending", limit=None)):
                raise ServiceError(409, "Ya hay un pago en proceso: espera su resultado.")
            row = {"id": uid(), "user_id": user_id, "provider": "mercadopago", "mode": plans.mode(), "tier": tier,
                   "plan_id": plan.plan_id, "provider_ref": None, "status": "pending", "period_end": None,
                   "grace_until": None, "ends_at": None, "last_reset_at": None, "last_payment_ref": None,
                   "replaces_id": active["id"] if active else None, "error": None, "created_at": at,
                   "updated_at": at}
            db.add(TABLE, **row)
            audit(db, user_id, "billing.checkout", row["id"])
            return row

    def fail(self, subscription_id: str, message: str) -> None:
        with self.store.transaction(write=True) as db:
            row = db.one(TABLE, id=subscription_id)
            if row and row["status"] == "pending":
                db.change(TABLE, subscription_id, status="failed", error=message[:1000], updated_at=_now())

    def create_remote(self, subscription_id: str, card_token: str, payer_email: str, retry: bool = False) -> str:
        """Billing worker: create the preapproval; ResourceUnavailable propagates so the task retries.

        On a retry the previous attempt may have reached Mercado Pago with its answer lost: look the preapproval
        up by external_reference first, so a retry never creates (and charges) a second subscription."""
        with self.store.transaction() as db:
            row = db.one(TABLE, id=subscription_id)
        if not row or row["status"] != "pending":
            return "skipped"
        if retry:
            existing = mercadopago.find_preapproval(row["mode"], row["id"], http_client=self.http_client)
            if existing:
                return self.apply_preapproval({**existing, "external_reference": row["id"]})
        body = {"preapproval_plan_id": row["plan_id"], "card_token_id": card_token, "payer_email": payer_email,
                "external_reference": row["id"], "back_url": public_url("/plans"), "status": "authorized"}
        try:
            resource = mercadopago.create_preapproval(row["mode"], body, idempotency_key=row["id"],
                                                      http_client=self.http_client)
        except mercadopago.GatewayRejected as exc:
            self.fail(row["id"], f"Mercado Pago rechazó el pago: {exc}")
            return "failed"
        except LookupError as exc:
            self.fail(row["id"], f"Pagos no configurados en este entorno ({exc})")
            return "failed"
        return self.apply_preapproval({**resource, "external_reference": resource.get("external_reference")
                                       or row["id"]})

    # Mercado Pago events ------------------------------------------------------------------------------
    def apply_event(self, topic: str, resource: dict) -> str:
        if topic == "subscription_preapproval":
            return self.apply_preapproval(resource)
        if topic == "subscription_authorized_payment":
            return self.apply_authorized_payment(resource)
        return "ignored"

    @staticmethod
    def _find(db, preapproval_id=None, reference=None):
        row = db.one(TABLE, provider="mercadopago", provider_ref=str(preapproval_id)) if preapproval_id else None
        if row is None and reference:
            row = db.one(TABLE, id=str(reference), provider="mercadopago")
        return row

    def _activate(self, db, row: dict, at: int, next_payment=None) -> dict | None:
        """Authorize `row`, load its budget and retire the subscription it replaces (returned for remote cancel)."""
        _grant(db, row, at)
        period_end = _parse_time(next_payment)
        db.change(TABLE, row["id"], status="authorized", period_end=period_end if period_end and period_end > at
                  else at + PERIOD, last_reset_at=at, grace_until=None, error=None, updated_at=at)
        audit(db, row["user_id"], "billing.activate", row["id"])
        old = db.one(TABLE, id=row["replaces_id"]) if row.get("replaces_id") else None
        if not old or old["status"] in ("replaced", "expired", "failed"):
            return None
        remote = old["provider"] == "mercadopago" and old.get("provider_ref") and old["status"] != "cancelled"
        db.change(TABLE, old["id"], status="replaced", ends_at=at, updated_at=at,
                  error=REMOTE_CANCEL_PENDING if remote else old.get("error"))
        _set_budget_active(db, old["id"], False)
        return old if remote else None

    def _cancel_remote(self, old: dict | None) -> None:
        if not old:
            return
        try:
            mercadopago.cancel_preapproval(old["mode"] or plans.mode(), old["provider_ref"], http_client=self.http_client)
        except Exception:
            logger.exception("Could not cancel replaced preapproval %s; enforce() retries", old["provider_ref"])
            return
        with self.store.transaction(write=True) as db:
            db.change(TABLE, old["id"], error=None, updated_at=_now())

    def apply_preapproval(self, resource: dict) -> str:
        at, status = _now(), resource.get("status")
        old, outcome = None, "ignored"
        with self.store.transaction(write=True) as db:
            row = self._find(db, resource.get("id"), resource.get("external_reference"))
            if row is None:
                return "unknown"
            if resource.get("id") and not row.get("provider_ref"):
                db.change(TABLE, row["id"], provider_ref=str(resource["id"]), updated_at=at)
                row = db.one(TABLE, id=row["id"])
            if status == "authorized" and row["status"] in ("pending", "failed"):
                old, outcome = self._activate(db, row, at, resource.get("next_payment_date")), "activated"
            elif status == "paused" and row["status"] == "authorized":
                db.change(TABLE, row["id"], status="past_due", grace_until=at + grace_seconds(), updated_at=at)
                outcome = "past_due"
            elif status == "cancelled" and row["status"] == "pending":
                db.change(TABLE, row["id"], status="failed", error="La suscripción fue cancelada antes de activarse",
                          updated_at=at)
                outcome = "failed"
            elif status == "cancelled" and row["status"] in ("authorized", "past_due"):
                # Cancelled by the payer: access until the end of the period already paid.
                db.change(TABLE, row["id"], status="cancelled", ends_at=max(row.get("period_end") or at, at),
                          updated_at=at)
                outcome = "cancelled"
        self._cancel_remote(old)
        return outcome

    def apply_authorized_payment(self, resource: dict) -> str:
        at = _now()
        payment = resource.get("payment") or {}
        reference = str(resource.get("id") or payment.get("id") or "")
        old, outcome = None, "ignored"
        with self.store.transaction(write=True) as db:
            row = self._find(db, resource.get("preapproval_id"))
            if row is None:
                return "unknown"
            if payment.get("status") == "approved":
                if reference and row.get("last_payment_ref") == reference:
                    return "duplicate"
                if row["status"] in ("pending", "failed"):
                    old, outcome = self._activate(db, row, at), "activated"
                elif row["status"] in ("authorized", "past_due", "suspended"):
                    reset = not row.get("last_reset_at") or at - row["last_reset_at"] >= reset_min_seconds()
                    if reset:
                        _grant(db, row, at)
                    else:
                        _set_budget_active(db, row["id"], True)
                    db.change(TABLE, row["id"], status="authorized", grace_until=None, error=None,
                              period_end=max(row.get("period_end") or at, at) + (PERIOD if reset else 0),
                              last_reset_at=at if reset else row.get("last_reset_at"), updated_at=at)
                    outcome = "renewed" if reset else "paid"
                db.change(TABLE, row["id"], last_payment_ref=reference or None, updated_at=at)
            elif (payment.get("status") in ("rejected", "cancelled") or resource.get("status") == "recycling") \
                    and row["status"] == "authorized":
                db.change(TABLE, row["id"], status="past_due", grace_until=at + grace_seconds(), updated_at=at)
                outcome = "past_due"
        self._cancel_remote(old)
        return outcome

    # Periodic enforcement -------------------------------------------------------------------------------
    def enforce(self, at: int | None = None) -> dict:
        at = at or _now()
        counts = {"suspended": 0, "expired": 0, "recharged": 0, "timed_out": 0}
        retry_cancel = []
        with self.store.transaction(write=True) as db:
            for row in db.many(TABLE, limit=None):
                status = row["status"]
                if status == "past_due" and (row.get("grace_until") or 0) <= at:
                    db.change(TABLE, row["id"], status="suspended", updated_at=at)
                    _set_budget_active(db, row["id"], False)
                    counts["suspended"] += 1
                elif status == "cancelled" and (row.get("ends_at") or 0) <= at:
                    db.change(TABLE, row["id"], status="expired", updated_at=at)
                    _set_budget_active(db, row["id"], False)
                    counts["expired"] += 1
                elif status == "authorized" and row["provider"] == "license":
                    if (row.get("ends_at") or 0) <= at:
                        db.change(TABLE, row["id"], status="expired", updated_at=at)
                        _set_budget_active(db, row["id"], False)
                        counts["expired"] += 1
                    elif (row.get("period_end") or 0) <= at:
                        period_end = row.get("period_end") or at
                        while period_end <= at:
                            period_end += PERIOD
                        _grant(db, row, at)
                        db.change(TABLE, row["id"], period_end=min(period_end, row["ends_at"]), last_reset_at=at,
                                  updated_at=at)
                        counts["recharged"] += 1
                elif status == "pending" and at - row["created_at"] >= PENDING_TIMEOUT:
                    db.change(TABLE, row["id"], status="failed", updated_at=at,
                              error="El pago no se completó a tiempo. Inténtalo de nuevo.")
                    counts["timed_out"] += 1
                elif status == "replaced" and row.get("error") == REMOTE_CANCEL_PENDING:
                    retry_cancel.append(row)
        for row in retry_cancel:
            self._cancel_remote(row)
        return counts

    # Licenses -------------------------------------------------------------------------------------------
    def create_licenses(self, actor_id: str, tier: str, months: int, count: int, note: str | None = None,
                        redeem_days: int | None = None) -> list[dict]:
        if plans.get(tier) is None:
            raise ServiceError(404, "Plan no encontrado")
        at, created = _now(), []
        with self.store.transaction(write=True) as db:
            for _ in range(count):
                code = new_code()
                row = {"id": uid(), "code_hash": code_hash(code), "code_hint": normalize_code(code)[-4:], "tier": tier,
                       "months": months, "note": (note or "")[:200] or None, "created_by": actor_id, "created_at": at,
                       "redeem_before": at + redeem_days * DAY if redeem_days else None, "redeemed_by": None,
                       "redeemed_at": None, "revoked_at": None}
                db.add(LICENSES, **row)
                audit(db, actor_id, "billing.license.create", row["id"])
                created.append({"id": row["id"], "code": code, "tier": tier, "months": months,
                                "redeem_before": row["redeem_before"]})
        return created

    def list_licenses(self, limit: int = 200) -> list[dict]:
        with self.store.transaction() as db:
            rows = sorted(db.many(LICENSES, limit=None), key=lambda row: row["created_at"], reverse=True)[:limit]
            emails = {}
            for row in rows:
                if row["redeemed_by"] and row["redeemed_by"] not in emails:
                    user = db.one("users", id=row["redeemed_by"])
                    emails[row["redeemed_by"]] = user["email"] if user else None
        return [{key: row[key] for key in ("id", "code_hint", "tier", "months", "note", "created_at", "redeem_before",
                                           "redeemed_at", "revoked_at")}
                | {"redeemed_by_email": emails.get(row["redeemed_by"])} for row in rows]

    def revoke_license(self, actor_id: str, license_id: str) -> dict:
        at = _now()
        with self.store.transaction(write=True) as db:
            row = db.one(LICENSES, id=license_id)
            if row is None:
                raise ServiceError(404, "Licencia no encontrada")
            if not row["revoked_at"]:
                db.change(LICENSES, license_id, revoked_at=at)
            subscription = db.one(TABLE, provider="license", provider_ref=license_id)
            if subscription and subscription["status"] == "authorized":
                db.change(TABLE, subscription["id"], status="expired", ends_at=at, updated_at=at)
                _set_budget_active(db, subscription["id"], False)
            audit(db, actor_id, "billing.license.revoke", license_id)
        return {"id": license_id, "revoked_at": row["revoked_at"] or at}

    def redeem(self, user_id: str, code: str) -> dict:
        at = _now()
        with self.store.transaction(write=True) as db:
            license_row = db.one(LICENSES, code_hash=code_hash(code)) if normalize_code(code) else None
            if license_row is None or license_row["revoked_at"]:
                raise ServiceError(404, "Código inválido")
            if license_row["redeemed_at"]:
                raise ServiceError(409, "Este código ya fue usado")
            if license_row["redeem_before"] and license_row["redeem_before"] < at:
                raise ServiceError(410, "Este código venció")
            if plans.get(license_row["tier"]) is None:
                raise ServiceError(409, "El plan de este código ya no está disponible")
            active = current(db, user_id, at)
            if active:
                raise ServiceError(409, f"Ya tienes el plan {active['tier']} activo; el código no se usó.")
            row = {"id": uid(), "user_id": user_id, "provider": "license", "mode": None, "tier": license_row["tier"],
                   "plan_id": None, "provider_ref": license_row["id"], "status": "authorized",
                   "period_end": at + PERIOD, "grace_until": None, "ends_at": at + license_row["months"] * PERIOD,
                   "last_reset_at": at, "last_payment_ref": None, "replaces_id": None, "error": None,
                   "created_at": at, "updated_at": at}
            db.add(TABLE, **row)
            _grant(db, row, at)
            db.change(LICENSES, license_row["id"], redeemed_by=user_id, redeemed_at=at)
            audit(db, user_id, "billing.license.redeem", license_row["id"])
            return self._view(db, row)
