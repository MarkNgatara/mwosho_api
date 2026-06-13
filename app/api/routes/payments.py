import base64
import logging

import requests as http_requests
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import BillingCycle, SubscriptionTier, User
from app.utils.helpers import get_current_user

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/payments", tags=["payments"])

_VALID_PLANS  = frozenset({"pro", "enterprise"})
_VALID_CYCLES = frozenset({"monthly", "yearly"})

# ── PayPal helpers ────────────────────────────────────────────────────────────

def _paypal_base() -> str:
    return "https://api-m.sandbox.paypal.com" if settings.PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"


def _paypal_token() -> str:
    creds = base64.b64encode(f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()).decode()
    r = http_requests.post(
        f"{_paypal_base()}/v1/oauth2/token",
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials",
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _verify_paypal_signature(headers: dict, payload: dict) -> bool:
    """Verify PayPal webhook signature via PayPal's verify-webhook-signature API.
    Returns False (rejects) if PAYPAL_WEBHOOK_ID is not configured.
    """
    if not settings.PAYPAL_WEBHOOK_ID:
        logger.error("PAYPAL_WEBHOOK_ID not configured — rejecting webhook")
        return False
    try:
        token = _paypal_token()
        r = http_requests.post(
            f"{_paypal_base()}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "auth_algo":        headers.get("paypal-auth-algo"),
                "cert_url":         headers.get("paypal-cert-url"),
                "transmission_id":  headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time":headers.get("paypal-transmission-time"),
                "webhook_id":       settings.PAYPAL_WEBHOOK_ID,
                "webhook_event":    payload,
            },
            timeout=10,
        )
        if not r.ok:
            logger.warning("PayPal signature verify call failed: %s %s", r.status_code, r.text)
            return False
        return r.json().get("verification_status") == "SUCCESS"
    except Exception as exc:
        logger.exception("PayPal signature verification error: %s", exc)
        return False


PAYPAL_PLAN_MAP: dict[tuple[str, str], str] = {
    ("pro",        "monthly"): settings.PAYPAL_PRO_PLAN_MONTHLY,
    ("pro",        "yearly"):  settings.PAYPAL_PRO_PLAN_YEARLY,
    ("enterprise", "monthly"): settings.PAYPAL_ENTERPRISE_PLAN_MONTHLY,
    ("enterprise", "yearly"):  settings.PAYPAL_ENTERPRISE_PLAN_YEARLY,
}

# Map plan+cycle → Stripe price ID (set in .env)
PRICE_MAP: dict[tuple[str, str], str] = {
    ("pro",        "monthly"): settings.STRIPE_PRO_PRICE_MONTHLY,
    ("pro",        "yearly"):  settings.STRIPE_PRO_PRICE_YEARLY,
    ("enterprise", "monthly"): settings.STRIPE_ENTERPRISE_PRICE_MONTHLY,
    ("enterprise", "yearly"):  settings.STRIPE_ENTERPRISE_PRICE_YEARLY,
}

TIER_MAP = {
    "pro":        SubscriptionTier.PRO,
    "enterprise": SubscriptionTier.ENTERPRISE,
}


class CheckoutRequest(BaseModel):
    plan: str
    cycle: str

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        if v not in _VALID_PLANS:
            raise ValueError(f"plan must be one of {sorted(_VALID_PLANS)}")
        return v

    @field_validator("cycle")
    @classmethod
    def validate_cycle(cls, v: str) -> str:
        if v not in _VALID_CYCLES:
            raise ValueError(f"cycle must be one of {sorted(_VALID_CYCLES)}")
        return v


@router.post("/checkout")
def create_checkout_session(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    price_id = PRICE_MAP.get((body.plan, body.cycle))
    if not price_id:
        raise HTTPException(status_code=400, detail="Stripe is not configured for this plan")

    # Create / retrieve Stripe customer
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            name=current_user.full_name or "",
            metadata={"user_id": str(current_user.id)},
        )
        current_user.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=current_user.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.FRONTEND_URL}/dashboard?upgraded=1",
        cancel_url=f"{settings.FRONTEND_URL}/#pricing",
        metadata={"user_id": str(current_user.id), "plan": body.plan, "cycle": body.cycle},
        allow_promotion_codes=True,
        billing_address_collection="auto",
    )
    return {"url": session.url}


@router.post("/portal")
def customer_portal(
    current_user: User = Depends(get_current_user),
):
    """Redirect user to Stripe billing portal to manage/cancel subscription."""
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")
    session = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=f"{settings.FRONTEND_URL}/dashboard/billing",
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        _handle_checkout_completed(db, data)

    elif event["type"] in ("customer.subscription.updated", "customer.subscription.deleted"):
        _handle_subscription_change(db, data)

    return {"status": "ok"}


def _handle_checkout_completed(db: Session, session: dict):
    meta = session.get("metadata", {})
    user_id = meta.get("user_id")
    plan = meta.get("plan")
    cycle = meta.get("cycle", "monthly")
    if not user_id or not plan:
        return

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return

    user.subscription_tier = TIER_MAP.get(plan, SubscriptionTier.FREE)
    user.billing_cycle = BillingCycle.YEARLY if cycle == "yearly" else BillingCycle.MONTHLY
    user.stripe_subscription_id = session.get("subscription")
    user.jobs_used_this_month = 0
    db.commit()


def _handle_subscription_change(db: Session, sub: dict):
    stripe_customer_id = sub.get("customer")
    if not stripe_customer_id:
        return
    user = db.query(User).filter(User.stripe_customer_id == stripe_customer_id).first()
    if not user:
        return

    status = sub.get("status")
    if status in ("canceled", "unpaid", "past_due"):
        user.subscription_tier = SubscriptionTier.FREE
        user.stripe_subscription_id = None
    elif status == "active":
        meta = sub.get("metadata", {})
        plan = meta.get("plan")
        if plan:
            user.subscription_tier = TIER_MAP.get(plan, user.subscription_tier)
    db.commit()


# ── PayPal endpoints ──────────────────────────────────────────────────────────

@router.post("/paypal/checkout")
def paypal_checkout(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
):
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="PayPal is not configured")

    # Prevent creating a duplicate subscription for the same tier
    requested_tier = TIER_MAP.get(body.plan)
    if requested_tier and current_user.subscription_tier == requested_tier:
        raise HTTPException(
            status_code=400,
            detail="You already have this subscription tier active.",
        )

    plan_id = PAYPAL_PLAN_MAP.get((body.plan, body.cycle))
    if not plan_id:
        raise HTTPException(status_code=400, detail="PayPal plan not configured for this tier")

    try:
        token = _paypal_token()
        r = http_requests.post(
            f"{_paypal_base()}/v1/billing/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "plan_id": plan_id,
                "subscriber": {"email_address": current_user.email},
                # custom_id encodes identity on the server side — never trust client-supplied values
                "custom_id": f"{current_user.id}|{body.plan}|{body.cycle}",
                "application_context": {
                    "brand_name": "Mwosho",
                    "return_url": f"{settings.FRONTEND_URL}/dashboard?upgraded=1",
                    "cancel_url": f"{settings.FRONTEND_URL}/#pricing",
                    "user_action": "SUBSCRIBE_NOW",
                    "shipping_preference": "NO_SHIPPING",
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        sub = r.json()
        approve_url = next(link["href"] for link in sub["links"] if link["rel"] == "approve")
        return {"url": approve_url}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PayPal checkout error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=502, detail="Could not initiate PayPal checkout")


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    """PayPal sends BILLING.SUBSCRIPTION.* events. Signature is verified before any DB writes."""
    raw_headers = dict(request.headers)
    payload = await request.json()

    if not _verify_paypal_signature(raw_headers, payload):
        logger.warning(
            "Rejected PayPal webhook — signature invalid. transmission_id=%s",
            raw_headers.get("paypal-transmission-id"),
        )
        raise HTTPException(status_code=400, detail="Webhook signature verification failed")

    event_type = payload.get("event_type", "")
    resource   = payload.get("resource", {})
    custom_id  = resource.get("custom_id", "")

    if not custom_id:
        return {"status": "ok"}

    parts = custom_id.split("|")

    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED" and len(parts) == 3:
        user_id_str, plan, cycle = parts
        if plan not in _VALID_PLANS or cycle not in _VALID_CYCLES:
            logger.warning("PayPal webhook has invalid plan/cycle in custom_id: %s", custom_id)
            return {"status": "ok"}
        try:
            user = db.query(User).filter(User.id == int(user_id_str)).first()
        except ValueError:
            return {"status": "ok"}
        if user:
            user.subscription_tier = TIER_MAP.get(plan, SubscriptionTier.FREE)
            user.billing_cycle = BillingCycle.YEARLY if cycle == "yearly" else BillingCycle.MONTHLY
            user.jobs_used_this_month = 0
            db.commit()
            logger.info("PayPal activated %s/%s for user %s", plan, cycle, user_id_str)

    elif event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED") and parts:
        try:
            user = db.query(User).filter(User.id == int(parts[0])).first()
        except ValueError:
            return {"status": "ok"}
        if user:
            user.subscription_tier = SubscriptionTier.FREE
            db.commit()
            logger.info("PayPal cancelled subscription for user %s", parts[0])

    return {"status": "ok"}
