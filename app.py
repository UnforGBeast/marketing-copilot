"""
Streamlit Frontend for Marketing Analytics Copilot SaaS.

Handles authentication, subscription management, and the core chat interface.
"""
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
MAX_MESSAGE_LENGTH = 2000

st.set_page_config(
    page_title="Marketing Analytics Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

def _init_session():
    defaults = {
        "auth_token": None,
        "refresh_token": None,
        "user_info": None,       # {user_id, email, full_name, plan}
        "usage_info": None,      # populated after login
        "messages": [],
        "processed_file_id": None,
        "confirm_clear": False,
        "auth_page": "login",    # "login" | "register"
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _welcome_message() -> Dict[str, str]:
    return {
        "role": "assistant",
        "content": (
            "**Welcome to Marketing Analytics Copilot!**\n\n"
            "I can help you with:\n\n"
            "- **Marketing Audits** — GTM configs, campaign ROI, tag validation\n"
            "- **Attribution Analysis** — channel mapping, multi-touch models\n"
            "- **KPI Strategy** — goal frameworks, metric definition\n"
            "- **General Questions** — best practices and guidance\n\n"
            "Upload a GTM JSON/CSV from the sidebar (Pro/Enterprise), or just ask a question."
        ),
    }


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _auth_headers() -> Dict[str, str]:
    token = st.session_state.get("auth_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _try_refresh() -> bool:
    """Attempt to get a new access token using the stored refresh token."""
    rt = st.session_state.get("refresh_token")
    if not rt:
        return False
    try:
        r = requests.post(
            f"{BACKEND_URL}/auth/refresh",
            json={"refresh_token": rt},
            timeout=10,
        )
        if r.status_code == 200:
            st.session_state.auth_token = r.json()["access_token"]
            return True
    except Exception:
        pass
    return False


def api_get(path: str, **kwargs) -> Optional[Dict]:
    try:
        r = requests.get(f"{BACKEND_URL}{path}", headers=_auth_headers(), timeout=15, **kwargs)
        if r.status_code == 401 and _try_refresh():
            r = requests.get(f"{BACKEND_URL}{path}", headers=_auth_headers(), timeout=15, **kwargs)
        if r.status_code == 200:
            return r.json()
        logger.warning("GET %s returned %s", path, r.status_code)
        return None
    except Exception as exc:
        logger.error("GET %s error: %s", path, exc)
        return None


def api_post(path: str, json_body: Optional[dict] = None, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.post(
            f"{BACKEND_URL}{path}",
            headers=_auth_headers(),
            json=json_body,
            timeout=30,
            **kwargs,
        )
        if r.status_code == 401 and _try_refresh():
            r = requests.post(
                f"{BACKEND_URL}{path}",
                headers=_auth_headers(),
                json=json_body,
                timeout=30,
                **kwargs,
            )
        return r
    except Exception as exc:
        logger.error("POST %s error: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------

def _page_login():
    st.title("📊 Marketing Analytics Copilot")
    st.markdown("Sign in to your account")

    col, _ = st.columns([1, 1])
    with col:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            if not email or not password:
                st.error("Please enter your email and password.")
            else:
                r = api_post("/auth/login", {"email": email, "password": password})
                if r is None:
                    st.error("Cannot reach the server. Is the backend running?")
                elif r.status_code == 200:
                    data = r.json()
                    st.session_state.auth_token = data["access_token"]
                    st.session_state.refresh_token = data["refresh_token"]
                    st.session_state.user_info = {
                        "user_id": data["user_id"],
                        "email": data["email"],
                        "full_name": data.get("full_name") or "",
                        "plan": data["plan"],
                    }
                    st.session_state.messages = [_welcome_message()]
                    _refresh_usage()
                    st.rerun()
                elif r.status_code == 401:
                    st.error("Invalid email or password.")
                else:
                    st.error(f"Login failed: {r.json().get('error', 'Unknown error')}")

        st.markdown("---")
        if st.button("Create a free account", use_container_width=True):
            st.session_state.auth_page = "register"
            st.rerun()


def _page_register():
    st.title("📊 Marketing Analytics Copilot")
    st.markdown("Create your free account")

    col, _ = st.columns([1, 1])
    with col:
        with st.form("register_form"):
            full_name = st.text_input("Full Name (optional)")
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input(
                "Password",
                type="password",
                help="Min 8 characters, must include uppercase, lowercase, and a digit",
            )
            confirm = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

        if submitted:
            if not email or not password:
                st.error("Email and password are required.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                r = api_post("/auth/register", {"email": email, "password": password, "full_name": full_name})
                if r is None:
                    st.error("Cannot reach the server.")
                elif r.status_code == 200:
                    data = r.json()
                    st.session_state.auth_token = data["access_token"]
                    st.session_state.refresh_token = data["refresh_token"]
                    st.session_state.user_info = {
                        "user_id": data["user_id"],
                        "email": data["email"],
                        "full_name": data.get("full_name") or "",
                        "plan": data["plan"],
                    }
                    st.session_state.messages = [_welcome_message()]
                    _refresh_usage()
                    st.success("Account created! Welcome aboard.")
                    st.rerun()
                elif r.status_code == 409:
                    st.error("An account with this email already exists.")
                elif r.status_code == 400:
                    st.error(r.json().get("error", "Invalid input."))
                else:
                    st.error("Registration failed. Please try again.")

        st.markdown("---")
        if st.button("Already have an account? Sign in", use_container_width=True):
            st.session_state.auth_page = "login"
            st.rerun()


# ---------------------------------------------------------------------------
# Usage refresh
# ---------------------------------------------------------------------------

def _refresh_usage():
    data = api_get("/user/usage")
    if data:
        st.session_state.usage_info = data
        if st.session_state.user_info:
            st.session_state.user_info["plan"] = data["plan"]


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------

def _call_chat_api(
    message: str,
    history: List[Dict[str, str]],
    uploaded_file=None,
) -> Optional[Dict[str, Any]]:
    data = {"message": message, "chat_history": json.dumps(history)}
    files = {}
    if uploaded_file:
        files["file"] = (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)

    try:
        r = requests.post(
            f"{BACKEND_URL}/chat",
            headers=_auth_headers(),
            data=data,
            files=files if files else None,
            timeout=90,
        )
        if r.status_code == 401 and _try_refresh():
            r = requests.post(
                f"{BACKEND_URL}/chat",
                headers=_auth_headers(),
                data=data,
                files=files if files else None,
                timeout=90,
            )

        if r.status_code == 200:
            _refresh_usage()
            return r.json()
        elif r.status_code == 401:
            st.error("Session expired. Please sign in again.")
            _logout()
        elif r.status_code == 403:
            st.warning(r.json().get("error", "Action not permitted on your current plan."))
        elif r.status_code == 429:
            st.warning(r.json().get("error", "Usage limit reached."))
        elif r.status_code == 503:
            st.error("AI service temporarily unavailable. Please try again.")
        else:
            st.error(f"Error {r.status_code}: {r.json().get('error', 'Unknown error')}")
        return None

    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend server.")
        return None
    except requests.exceptions.Timeout:
        st.error("Request timed out. The server may be processing a large file.")
        return None


def _export_conversation(messages: List[Dict]) -> str:
    exportable = [m for m in messages if m["role"] != "assistant" or "Welcome to" not in m["content"]]
    return json.dumps({
        "version": "2.0",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "conversation_id": str(uuid.uuid4()),
        "messages": exportable,
    }, indent=2)


def _import_conversation(uploaded_file) -> bool:
    try:
        data = json.loads(uploaded_file.getvalue())
        msgs = data.get("messages", [])
        if not msgs:
            st.error("No messages found in file.")
            return False
        st.session_state.messages = [_welcome_message()] + msgs
        st.success(f"Imported {len(msgs)} messages.")
        return True
    except Exception as exc:
        st.error(f"Import failed: {exc}")
        return False


def _logout():
    for key in ("auth_token", "refresh_token", "user_info", "usage_info", "messages"):
        st.session_state[key] = None if key not in ("messages",) else []
    st.session_state.auth_page = "login"
    st.rerun()


# ---------------------------------------------------------------------------
# Subscription sidebar section
# ---------------------------------------------------------------------------

def _sidebar_subscription():
    user = st.session_state.user_info or {}
    usage = st.session_state.usage_info or {}

    plan = user.get("plan", "free").capitalize()
    st.markdown(f"**Signed in as:** {user.get('email', '')}")
    st.markdown(f"**Plan:** {plan}")

    if usage:
        st.markdown("**Usage:**")
        daily_limit = usage.get("daily_limit")
        monthly_limit = usage.get("monthly_limit")
        today = usage.get("messages_today", 0)
        month = usage.get("messages_this_month", 0)

        if daily_limit:
            st.progress(min(today / daily_limit, 1.0), text=f"Today: {today}/{daily_limit}")
        else:
            st.caption(f"Today: {today} messages")

        if monthly_limit:
            st.progress(min(month / monthly_limit, 1.0), text=f"This month: {month}/{monthly_limit}")
        elif monthly_limit is None and user.get("plan") != "free":
            st.caption(f"This month: {month} messages (unlimited)")

    current_plan = user.get("plan", "free")
    if current_plan == "free":
        if st.button("Upgrade to Pro — $29/mo", use_container_width=True, type="primary"):
            r = api_post("/subscription/checkout", {"plan": "pro"})
            if r and r.status_code == 200:
                url = r.json().get("checkout_url")
                if url:
                    st.markdown(f"[Complete payment]({url})", unsafe_allow_html=True)
                    st.info("Click the link above to complete your upgrade.")
            else:
                msg = r.json().get("error", "Could not create checkout session.") if r else "Server error."
                st.error(msg)

        if st.button("Upgrade to Enterprise — $99/mo", use_container_width=True):
            r = api_post("/subscription/checkout", {"plan": "enterprise"})
            if r and r.status_code == 200:
                url = r.json().get("checkout_url")
                if url:
                    st.markdown(f"[Complete payment]({url})", unsafe_allow_html=True)
            else:
                msg = r.json().get("error", "Could not create checkout session.") if r else "Server error."
                st.error(msg)

    else:
        if st.button("Manage Billing", use_container_width=True):
            r = api_post("/subscription/portal")
            if r and r.status_code == 200:
                url = r.json().get("portal_url")
                if url:
                    st.markdown(f"[Open billing portal]({url})", unsafe_allow_html=True)
            else:
                msg = r.json().get("error", "Could not open billing portal.") if r else "Server error."
                st.error(msg)

    st.divider()
    if st.button("Sign Out", use_container_width=True):
        _logout()


# ---------------------------------------------------------------------------
# Main app page
# ---------------------------------------------------------------------------

def _page_app():
    # Handle Stripe redirect query params
    params = st.query_params
    if params.get("payment_status") == "success":
        st.success("Payment successful! Your plan has been upgraded.")
        _refresh_usage()
        st.query_params.clear()
    elif params.get("payment_status") == "cancelled":
        st.info("Payment cancelled. You remain on your current plan.")
        st.query_params.clear()

    st.title("📊 Marketing Analytics Copilot")

    with st.sidebar:
        st.header("Account")
        _sidebar_subscription()

        st.header("Conversation")
        messages = st.session_state.messages
        user_msgs = [m for m in messages if m["role"] == "user"]
        st.caption(f"{len(user_msgs)} messages in this session")

        if len(user_msgs) > 0:
            export_data = _export_conversation(messages)
            st.download_button(
                "Export Conversation",
                data=export_data,
                file_name=f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )

        import_file = st.file_uploader("Import Conversation", type=["json"], key="import_uploader")
        if import_file and st.button("Load", use_container_width=True):
            if _import_conversation(import_file):
                st.rerun()

        if len(user_msgs) > 0:
            if not st.session_state.confirm_clear:
                if st.button("Clear History", use_container_width=True):
                    st.session_state.confirm_clear = True
                    st.rerun()
            else:
                st.warning("This cannot be undone.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Clear", type="primary", use_container_width=True):
                        st.session_state.messages = [_welcome_message()]
                        st.session_state.confirm_clear = False
                        st.rerun()
                with c2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state.confirm_clear = False
                        st.rerun()

        st.divider()
        st.header("Upload File")

        usage = st.session_state.usage_info or {}
        can_upload = usage.get("file_uploads_allowed", False)

        if can_upload:
            max_mb = usage.get("max_file_size_mb", 10)
            uploaded_file = st.file_uploader(
                "GTM Configuration (JSON/CSV)",
                type=["json", "csv"],
                help=f"Max {max_mb} MB on your plan",
                key="file_uploader",
            )
            if uploaded_file:
                st.success(f"{uploaded_file.name} ({uploaded_file.size / 1024:.1f} KB)")
        else:
            uploaded_file = None
            st.info("File uploads require Pro or Enterprise. Upgrade from the Account section above.")

        st.divider()
        st.header("System Status")
        try:
            hr = requests.get(f"{BACKEND_URL}/", timeout=5)
            if hr.status_code == 200:
                st.success("Backend: Connected")
            else:
                st.error("Backend: Error")
        except Exception:
            st.error("Backend: Offline")

    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask about marketing analytics...", max_chars=MAX_MESSAGE_LENGTH):
        if not prompt.strip():
            st.warning("Please enter a message.")
            return

        display_msg = prompt
        if "uploaded_file" in dir() and uploaded_file:
            display_msg += f"\n\n*Attached: {uploaded_file.name}*"

        st.session_state.messages.append({"role": "user", "content": display_msg})
        with st.chat_message("user"):
            st.markdown(display_msg)

        # Filter welcome from history sent to backend
        history = [
            m for m in st.session_state.messages[:-1]
            if not (m["role"] == "assistant" and "Welcome to Marketing Analytics Copilot" in m["content"])
        ]

        with st.chat_message("assistant"):
            spinner_text = "Analyzing file and generating report..." if (can_upload and uploaded_file) else "Thinking..."
            with st.spinner(spinner_text):
                result = _call_chat_api(prompt, history, uploaded_file if can_upload else None)

            if result and result.get("status") == "success":
                text = result.get("response", "No response received.")
                st.markdown(text)
                st.session_state.messages.append({"role": "assistant", "content": text})
            # Error already shown by _call_chat_api

    st.divider()
    plan_name = (st.session_state.user_info or {}).get("plan", "free").capitalize()
    st.caption(f"Marketing Analytics Copilot v3.0.0 | Plan: {plan_name} | Powered by Gemini & LangChain")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    _init_session()

    if not st.session_state.auth_token:
        if st.session_state.auth_page == "register":
            _page_register()
        else:
            _page_login()
    else:
        _page_app()


if __name__ == "__main__":
    main()
