"""
FastAPI Backend for Marketing Analytics Copilot SaaS.

Provides REST API with JWT authentication, Stripe subscription management,
per-user usage enforcement, audit logging, and the core chat endpoint.
"""
import json
import logging
import sys
from datetime import date
from typing import Optional

import stripe
from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Request, UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_user,
    get_current_user,
    get_user_by_email,
    log_audit,
    refresh_access_token,
)
from database import Subscription, UsageRecord, get_db, init_db
from dependencies import record_file_upload, require_chat_access, require_file_upload
from dotenv import load_dotenv
import os
from orchestrator import OrchestratorError, get_orchestrator, process_query
from stripe_service import (
    PLANS,
    cancel_subscription_in_db,
    create_billing_portal,
    create_checkout_session,
    create_stripe_customer,
    get_plan,
    sync_subscription_from_stripe,
    verify_webhook,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_MB = 50  # hard ceiling; per-plan enforcement in dependencies.py
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_MESSAGE_LENGTH = 2000
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8501")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app + middleware
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Marketing Analytics Copilot API",
    description="SaaS API with JWT auth, Stripe subscriptions, and AI-powered marketing analytics.",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    max_age=3600,
)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = MAX_FILE_SIZE_BYTES + 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and int(cl) > self.max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"error": "Request too large", "status": "error"},
                )
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if os.getenv("ENVIRONMENT") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    msg = errors[0].get("msg", "Invalid request") if errors else "Invalid request"
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return JSONResponse(status_code=400, content={"error": msg, "status": "error"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": "error"},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error", "status": "error"})


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field("", max_length=255)

    @field_validator("password")
    def password_complexity(cls, v):
        import re
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    full_name: Optional[str]
    plan: str


class UserResponse(BaseModel):
    user_id: int
    email: str
    full_name: Optional[str]
    plan: str
    subscription_status: str
    member_since: str


class UsageResponse(BaseModel):
    plan: str
    plan_name: str
    messages_today: int
    messages_this_month: int
    daily_limit: Optional[int]
    monthly_limit: Optional[int]
    file_uploads_allowed: bool
    max_file_size_mb: int


class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern="^(pro|enterprise)$")


class QueryResponse(BaseModel):
    response: str
    status: str = "success"


class ErrorResponse(BaseModel):
    error: str
    status: str = "error"


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("Marketing Analytics Copilot SaaS API v3.0.0 - Starting")
    logger.info("=" * 60)
    init_db()
    logger.info("Database tables verified/created.")
    try:
        get_orchestrator()
        logger.info("AI Orchestrator initialized.")
    except OrchestratorError as exc:
        logger.critical("FATAL: AI Orchestrator failed to start: %s", exc)
        sys.exit(1)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Marketing Analytics Copilot SaaS API - Shutting down")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "Marketing Analytics Copilot API", "version": "3.0.0"}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=TokenResponse, tags=["Auth"])
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if get_user_by_email(db, body.email):
        log_audit(db, "register_failed", ip_address=ip, details=f"Duplicate email: {body.email}", success=False)
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    try:
        user = create_user(db, body.email, body.password, body.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    log_audit(db, "register", user_id=user.id, ip_address=ip)
    plan = user.subscription.plan if user.subscription else "free"
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        plan=plan,
    )


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    user = authenticate_user(db, body.email, body.password)
    if not user:
        log_audit(db, "login_failed", ip_address=ip, details=body.email, success=False)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    log_audit(db, "login", user_id=user.id, ip_address=ip)
    plan = user.subscription.plan if user.subscription else "free"
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        plan=plan,
    )


@app.post("/auth/refresh", tags=["Auth"])
@limiter.limit("30/minute")
async def refresh(request: Request, body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        new_access = refresh_access_token(body.refresh_token, db)
    except HTTPException:
        raise
    return {"access_token": new_access, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------

@app.get("/user/me", response_model=UserResponse, tags=["User"])
async def get_me(current_user=Depends(get_current_user)):
    sub = current_user.subscription
    return UserResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        plan=sub.plan if sub else "free",
        subscription_status=sub.status if sub else "none",
        member_since=current_user.created_at.strftime("%Y-%m-%d"),
    )


@app.get("/user/usage", response_model=UsageResponse, tags=["User"])
async def get_usage(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    messages_today = usage_today.messages_count if usage_today else 0

    monthly_total = (
        db.query(func.sum(UsageRecord.messages_count))
        .filter(UsageRecord.user_id == current_user.id, UsageRecord.date >= month_start)
        .scalar()
    ) or 0

    return UsageResponse(
        plan=plan_name,
        plan_name=limits["name"],
        messages_today=messages_today,
        messages_this_month=int(monthly_total),
        daily_limit=limits["messages_per_day"],
        monthly_limit=limits["messages_per_month"],
        file_uploads_allowed=limits["file_uploads"],
        max_file_size_mb=limits["max_file_size_mb"],
    )


# ---------------------------------------------------------------------------
# Subscription endpoints
# ---------------------------------------------------------------------------

@app.get("/subscription", tags=["Subscription"])
async def get_subscription(current_user=Depends(get_current_user)):
    sub = current_user.subscription
    plan_name = sub.plan if sub else "free"
    limits = get_plan(plan_name)
    return {
        "plan": plan_name,
        "plan_details": limits,
        "status": sub.status if sub else "none",
        "current_period_end": (
            sub.current_period_end.isoformat() if sub and sub.current_period_end else None
        ),
        "available_plans": {k: {
            "name": v["name"],
            "price_usd": v["price_usd"],
            "description": v["description"],
        } for k, v in PLANS.items()},
    }


@app.post("/subscription/checkout", tags=["Subscription"])
@limiter.limit("10/minute")
async def create_checkout(
    request: Request,
    body: CheckoutRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan_data = get_plan(body.plan)
    if not plan_data.get("price_id"):
        raise HTTPException(status_code=400, detail="Stripe price ID not configured for this plan")

    sub = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    if not sub:
        raise HTTPException(status_code=500, detail="Subscription record missing")

    if not sub.stripe_customer_id:
        customer_id = create_stripe_customer(current_user.email, current_user.full_name or "")
        sub.stripe_customer_id = customer_id
        db.commit()

    try:
        checkout_url = create_checkout_session(
            customer_id=sub.stripe_customer_id,
            price_id=plan_data["price_id"],
            user_id=current_user.id,
            success_url=f"{FRONTEND_URL}?payment_status=success",
            cancel_url=f"{FRONTEND_URL}?payment_status=cancelled",
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe checkout error: %s", exc)
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")

    log_audit(db, "checkout_initiated", user_id=current_user.id, details=body.plan)
    return {"checkout_url": checkout_url}


@app.post("/subscription/portal", tags=["Subscription"])
@limiter.limit("10/minute")
async def billing_portal(
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found. Subscribe to a plan first.")

    try:
        portal_url = create_billing_portal(sub.stripe_customer_id, FRONTEND_URL)
    except stripe.error.StripeError as exc:
        logger.error("Stripe portal error: %s", exc)
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")

    return {"portal_url": portal_url}


# ---------------------------------------------------------------------------
# Stripe webhook (no auth — verified by signature)
# ---------------------------------------------------------------------------

@app.post("/webhook/stripe", tags=["Webhook"], include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook(payload, sig)
    except ValueError as exc:
        logger.warning("Invalid Stripe webhook: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook")

    etype = event["type"]
    data = event["data"]["object"]
    logger.info("Stripe webhook received: %s", etype)

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        sync_subscription_from_stripe(db, data)
    elif etype == "customer.subscription.deleted":
        cancel_subscription_in_db(db, data["id"])
    elif etype == "invoice.payment_failed":
        stripe_sub_id = data.get("subscription")
        if stripe_sub_id:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_sub_id
            ).first()
            if sub:
                sub.status = "past_due"
                db.commit()

    return {"received": True}


# ---------------------------------------------------------------------------
# Chat endpoint (protected)
# ---------------------------------------------------------------------------

@app.post(
    "/chat",
    response_model=QueryResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    tags=["Chat"],
)
@limiter.limit("30/minute")
@limiter.limit("200/hour")
async def chat_endpoint(
    request: Request,
    message: str = Form(..., min_length=1, max_length=MAX_MESSAGE_LENGTH),
    file: Optional[UploadFile] = File(None),
    chat_history: str = Form("[]"),
    current_user=Depends(require_chat_access),
    db: Session = Depends(get_db),
):
    if not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Parse history
    parsed_history = []
    if chat_history and chat_history != "[]":
        try:
            parsed_history = json.loads(chat_history)
        except json.JSONDecodeError:
            parsed_history = []

    file_content: Optional[str] = None
    file_type: Optional[str] = None

    if file:
        sub = current_user.subscription
        plan_name = sub.plan if sub else "free"
        plan_limits = get_plan(plan_name)

        if not plan_limits["file_uploads"]:
            raise HTTPException(
                status_code=403,
                detail="File uploads require a Pro or Enterprise subscription.",
            )

        if not file.filename.endswith((".json", ".csv")):
            raise HTTPException(status_code=400, detail="Only JSON and CSV files are supported.")

        content_bytes = await file.read()
        if len(content_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        max_bytes = plan_limits["max_file_size_mb"] * 1024 * 1024
        if len(content_bytes) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Your plan allows up to {plan_limits['max_file_size_mb']} MB.",
            )

        try:
            file_content = content_bytes.decode("utf-8")
            record_file_upload(current_user.id, db)
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

        file_type = "json" if file.filename.endswith(".json") else "csv"

    try:
        response_text = await process_query(
            message.strip(), file_content, file_type, parsed_history
        )
        logger.info("Chat response generated for user %s", current_user.id)
        return QueryResponse(response=response_text)
    except OrchestratorError:
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
