import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import BillingCycle, SubscriptionTier, User
from app.utils.helpers import get_current_user

stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/payments", tags=["payments"])

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
    plan: str   # "pro" | "enterprise"
    cycle: str  # "monthly" | "yearly"


@router.post("/checkout")
def create_checkout_session(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    price_id = PRICE_MAP.get((body.plan, body.cycle))
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan or cycle")

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
        # Re-sync plan from Stripe metadata if available
        meta = sub.get("metadata", {})
        plan = meta.get("plan")
        if plan:
            user.subscription_tier = TIER_MAP.get(plan, user.subscription_tier)
    db.commit()
