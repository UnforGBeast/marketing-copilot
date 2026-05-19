"""
FastAPI dependencies for subscription enforcement and usage tracking.
"""
from datetime import date

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import User, UsageRecord, get_db
from stripe_service import get_plan


async def require_chat_access(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Enforce plan message limits and record usage for each /chat call."""
    sub = current_user.subscription
    plan_name = sub.plan if sub else "free"
    limits = get_plan(plan_name)

    today = str(date.today())
    month_start = today[:7] + "-01"

    usage_today = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == current_user.id, UsageRecord.date == today)
        .first()
    )
    daily_count = usage_today.messages_count if usage_today else 0

    if limits["messages_per_day"] is not None and daily_count >= limits["messages_per_day"]:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily limit of {limits['messages_per_day']} messages reached. "
                "Upgrade to Pro for more."
            ),
        )

    monthly_total = (
        db.query(func.sum(UsageRecord.messages_count))
        .filter(UsageRecord.user_id == current_user.id, UsageRecord.date >= month_start)
        .scalar()
    ) or 0

    if limits["messages_per_month"] is not None and monthly_total >= limits["messages_per_month"]:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly limit of {limits['messages_per_month']} messages reached. "
                "Upgrade your plan to continue."
            ),
        )

    # Record message usage
    if not usage_today:
        usage_today = UsageRecord(user_id=current_user.id, date=today)
        db.add(usage_today)

    usage_today.messages_count += 1
    db.commit()

    return current_user


def record_file_upload(user_id: int, db: Session) -> None:
    """Increment file_uploads_count for today. Call from endpoint after file is accepted."""
    today = str(date.today())
    usage = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user_id, UsageRecord.date == today)
        .first()
    )
    if usage:
        usage.file_uploads_count += 1
        db.commit()


def require_file_upload(current_user: User = Depends(get_current_user)) -> User:
    """Block file uploads for Free plan users."""
    sub = current_user.subscription
    plan_name = sub.plan if sub else "free"
    limits = get_plan(plan_name)
    if not limits["file_uploads"]:
        raise HTTPException(
            status_code=403,
            detail="File uploads require a Pro or Enterprise subscription.",
        )
    return current_user
