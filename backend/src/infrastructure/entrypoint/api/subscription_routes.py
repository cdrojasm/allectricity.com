"""Plans, checkout, the user's subscription and license codes.

- GET  /api/v1/billing/catalog        public (landing): tier names, USD reference price and monthly tokens
- GET  /api/v1/billing/plans          tiers with the price charged by Mercado Pago and the public key for the Brick
- GET  /api/v1/billing/subscription   the user's plan, its token balance and the latest checkout
- POST /api/v1/billing/checkout       starts an asynchronous checkout (202); the billing worker charges the card
- POST /api/v1/billing/licenses/redeem
- Admin (super_admin): POST/GET /api/v1/billing/licenses, POST /api/v1/billing/licenses/{id}/revoke
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.domain.identity import ServiceError
from src.infrastructure.billing import mercadopago, plans
from src.infrastructure.billing.subscriptions import Subscriptions
from src.infrastructure.entrypoint.worker.tasks import create_mercadopago_subscription
from src.infrastructure.security.middleware import require

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    tier: str = Field(min_length=1, max_length=40)
    card_token: str = Field(min_length=8, max_length=200)
    payer_email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RedeemRequest(BaseModel):
    code: str = Field(min_length=6, max_length=40)


class LicenseRequest(BaseModel):
    tier: str = Field(min_length=1, max_length=40)
    months: int = Field(ge=1, le=36)
    count: int = Field(default=1, ge=1, le=100)
    note: str | None = Field(default=None, max_length=200)
    redeem_days: int | None = Field(default=None, ge=1, le=365)


def _service(request: Request) -> Subscriptions:
    return Subscriptions(request.app.state.services.store)


def _http(exc: ServiceError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _configured() -> list:
    try:
        return plans.configured()
    except plans.PlanConfigError as exc:
        log.error("Invalid MP_PLAN_* configuration: %s", exc)
        raise HTTPException(503, "Los planes no están configurados correctamente.") from exc


def _checkout_block(actor, mode: str) -> str | None:
    """Why this user cannot buy right now, or None.

    In test mode the published test cards would unlock real tokens for free, so by default only administrators
    can buy (MP_TEST_CHECKOUT=everyone opens it, e.g. locally). In production the credentials must belong to a
    real Mercado Pago account: a test seller accepts test cards."""
    if mode == "test":
        everyone = os.getenv("MP_TEST_CHECKOUT", "admins").strip().lower() == "everyone"
        return None if everyone or actor.privileged else "Los pagos aún no están habilitados. Usa un código de licencia."
    try:
        if mercadopago.account(mode)["test_user"]:
            log.error("MP_PROD_ACCESS_TOKEN belongs to a Mercado Pago test account: checkout disabled")
            return "Los pagos aún no están habilitados. Usa un código de licencia."
    except (LookupError, mercadopago.ResourceUnavailable, mercadopago.GatewayRejected):
        return "Los pagos no están disponibles en este momento. Inténtalo más tarde."
    return None


@router.get("/catalog")
def public_catalog():
    """Public, for the landing's pricing section: only what MP_PLAN_* already declares; no Mercado Pago call."""
    try:
        tiers = plans.configured()
    except plans.PlanConfigError as exc:
        log.error("Invalid MP_PLAN_* configuration: %s", exc)
        tiers = []
    return {"plans": [{"name": plan.name, "rank": plan.rank, "price_usd": plan.price_usd,
                       "monthly_tokens": plan.monthly_tokens} for plan in tiers]}


@router.get("/plans")
def list_plans(actor=Depends(require())):
    mode = plans.mode()
    public_key = plans.public_key(mode)
    blocked = _checkout_block(actor, mode)
    result = []
    for plan in _configured():
        info = plans.details(plan, mode)
        result.append({"name": plan.name, "rank": plan.rank, "price_usd": plan.price_usd,
                       "monthly_tokens": plan.monthly_tokens, "amount": info.get("amount"),
                       "currency": info.get("currency"), "frequency": info.get("frequency"),
                       "frequency_type": info.get("frequency_type"),
                       "available": bool(info.get("available") and public_key and info.get("amount")),
                       "unavailable_reason": info.get("unavailable_reason") or (None if info.get("available")
                                                                                 else info.get("reason"))})
    return {"mode": mode, "public_key": public_key or None, "plans": result,
            "checkout": {"enabled": blocked is None, "reason": blocked}}


@router.get("/subscription")
def my_subscription(request: Request, actor=Depends(require())):
    return _service(request).summary(actor.user_id)


@router.post("/checkout", status_code=202)
def checkout(payload: CheckoutRequest, request: Request, actor=Depends(require())):
    """Store a pending subscription and hand the card token to the billing worker; poll /subscription."""
    _configured()
    if blocked := _checkout_block(actor, plans.mode()):
        raise HTTPException(403, blocked)
    service = _service(request)
    try:
        row = service.start_checkout(actor.user_id, payload.tier)
    except ServiceError as exc:
        raise _http(exc) from exc
    try:
        create_mercadopago_subscription.delay(row["id"], payload.card_token, payload.payer_email)
    except Exception as exc:
        service.fail(row["id"], "No se pudo iniciar el cobro. Inténtalo de nuevo.")
        raise HTTPException(503, "No se pudo iniciar el cobro. Inténtalo de nuevo.") from exc
    return {"subscription_id": row["id"], "status": "pending"}


@router.post("/licenses/redeem")
async def redeem_license(payload: RedeemRequest, request: Request, actor=Depends(require())):
    services = request.app.state.services
    try:
        # Codes are not guessable (60 bits), and attempts per user are limited anyway.
        await run_in_threadpool(services.identity.throttle, "license_redeem", actor.user_id, 10, 600)
        return {"subscription": await run_in_threadpool(Subscriptions(services.store).redeem, actor.user_id,
                                                        payload.code)}
    except ServiceError as exc:
        raise _http(exc) from exc


@router.post("/licenses", status_code=201)
def create_licenses(payload: LicenseRequest, request: Request, actor=Depends(require(privileged=True))):
    _configured()
    try:
        codes = _service(request).create_licenses(actor.user_id, payload.tier, payload.months, payload.count,
                                                  payload.note, payload.redeem_days)
    except ServiceError as exc:
        raise _http(exc) from exc
    return {"licenses": codes, "notice": "Copia los códigos ahora: no se vuelven a mostrar."}


@router.get("/licenses")
def list_licenses(request: Request, _actor=Depends(require(privileged=True))):
    return {"licenses": _service(request).list_licenses()}


@router.post("/licenses/{license_id}/revoke")
def revoke_license(license_id: str, request: Request, actor=Depends(require(privileged=True))):
    try:
        return _service(request).revoke_license(actor.user_id, license_id)
    except ServiceError as exc:
        raise _http(exc) from exc
