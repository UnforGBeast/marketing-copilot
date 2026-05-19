"""
Stripe integration: customer creation, checkout sessions, billing portal, webhook handling.
"""
import os
from datetime import datetime
from typing import Optional

import stripe
from sqlalchemy.orm import Session

from database import Subscription

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# Plan definitions — single source of truth for limits and Stripe price IDs
# ---------------------------------------------------------------------------

PLANS: dict[str, dict] = {
    "free": {
        "name": "Free",
        "price_id": None,
        "messages_per_day": 10,
        "messages_per_month": None,
        "file_uploads": False,
        "max_file_size_mb": 0,
        "price_usd": 0,
        "description": "10 messages/day, no file uploads",
    },
    "pro": {
        "name": "Pro",
        "price_id": os.getenv("STRIPE_PRO_PRICE_ID", ""),
        "messages_per_day": None,
        "messages_per_month": 500,
        "file_uploads": True,
        "max_file_size_mb": 10,
        "price_usd": 29,
        "description": "500 messages/month, 10 MB file uploads",
    },
    "enterprise": {
        "name": "Enterprise",
        "price_id": os.getenv("STRIPE_ENTERPRISE_PRICE_ID", ""),
        "messages_per_day": None,
        "messages_per_month": None,
        "file_uploads": True,
        "max_file_size_mb": 50,
        "price_usd": 99,
        "description": "Unlimited messages, 50 MB file uploads",
    },
}


def get_plan(plan: str) -> dict:
    return PLANS.get(plan, PLANS["free"])


# ---------------------------------------------------------------------------
# Stripe API wrappers
# ---------------------------------------------------------------------------

def create_stripe_customer(email: str, name: str = "") -> str:
    customer = stripe.Customer.create(email=email, name=name or email)
    return customer.id


def create_checkout_session(
    customer_id: str,
    price_id: str,
    user_id: int,
    success_url: str,
    cancel_url: str,
) -> str:
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": str(user_id)},
        subscription_data={"metadata": {"user_id": str(user_id)}},
    )
    return session.url


def create_billing_portal(customer_id: str, return_url: str) -> str:
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    if not _WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
    try:
        return stripe.Webhook.construct_event(payload, sig_header, _WEBHOOK_SECRET)
    except ValueError as exc:
        raise ValueError(f"Invalid webhook payload: {exc}") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise ValueError(f"Webhook signature verification failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Database sync
# ---------------------------------------------------------------------------

def sync_subscription_from_stripe(
    db: Session, stripe_sub: dict, user_id: Optional[int] = None
) -> None:
    uid = user_id or int((stripe_sub.get("metadata") or {}).get("user_id", 0))
    if not uid:
        return

    sub = db.query(Subscription).filter(Subscription.user_id == uid).first()
    if not sub:
        return

    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    plan = next(
        (k for k, v in PLANS.items() if v.get("price_id") and v["price_id"] == price_id),
        "free",
    )

    sub.stripe_subscription_id = stripe_sub["id"]
    sub.plan = plan
    sub.status = stripe_sub["status"]
    sub.current_period_start = datetime.fromtimestamp(stripe_sub["current_period_start"])
    sub.current_period_end = datetime.fromtimestamp(stripe_sub["current_period_end"])
    db.commit()


def cancel_subscription_in_db(db: Session, stripe_sub_id: str) -> None:
    sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == stripe_sub_id
    ).first()
    if sub:
        sub.plan = "free"
        sub.status = "cancelled"
        sub.stripe_subscription_id = None
        db.commit()
