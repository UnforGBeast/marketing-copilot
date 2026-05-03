"""
Streamlit Frontend for Marketing Analytics Copilot.

This module provides the user interface for interacting with
the Marketing Analytics Copilot backend.
"""

import streamlit as st
import requests
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = "http://localhost:8001"
MAX_MESSAGE_LENGTH = 2000

# Page configuration
st.set_page_config(
    page_title="Marketing Analytics Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)


def initialize_session_state():
    """Initialize session state variables."""
    if "processed_file_id" not in st.session_state:
        st.session_state.processed_file_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": """👋 **Welcome to the Marketing Analytics Copilot!**

I'm your AI assistant for marketing analytics. I can help you with:

🔍 **Marketing Audits** - Performance reviews, campaign analysis, ROI assessments
📊 **Attribution Analysis** - Channel analysis, customer journey mapping, multi-touch attribution
🎯 **KPI Strategy** - Metric definition, goal setting, performance frameworks
💬 **General Questions** - Marketing advice, best practices, and guidance

**✨ NEW in Sprint 3: Conversation Memory!**
- I now remember our conversation context
- Ask follow-up questions naturally
- Reference previous topics without repeating yourself
- Multi-turn conversations with full context awareness

**Sprint 2 Features:**
- Upload GTM configurations (JSON/CSV) for comprehensive audits
- Get detailed reports with Critical Issues, Warnings, and Optimizations
- Powered by Gemini 2.5-flash with massive context window

**How to use:**
1. Upload a file using the sidebar (optional)
2. Ask your question or request an audit
3. Continue the conversation with follow-up questions
4. Get instant analysis and recommendations

How can I assist you today?"""
            }
        ]
        logger.info("Session state initialized with welcome message")


def call_backend_api(message: str, chat_history: List[Dict[str, str]], uploaded_file=None) -> Optional[Dict[str, Any]]:
    """
    Call the backend API with a user message, chat history, and optional file.
    
    Args:
        message: The user's message
        chat_history: List of previous conversation messages
        uploaded_file: Optional Streamlit UploadedFile object
        
    Returns:
        API response as dictionary, or None if error
    """
    try:
        logger.info(f"Calling backend API - Message length: {len(message)} chars, History: {len(chat_history)} msgs, File: {uploaded_file.name if uploaded_file else 'None'}")
        
        # Prepare multipart form data
        files = {}
        data = {
            "message": message,
            "chat_history": json.dumps(chat_history)  # Serialize history to JSON string
        }
        
        if uploaded_file:
            files["file"] = (
                uploaded_file.name,
                uploaded_file.getvalue(),
                uploaded_file.type
            )
            logger.info(f"Uploading file: {uploaded_file.name} ({uploaded_file.size} bytes)")
        
        response = requests.post(
            f"{BACKEND_URL}/chat",
            data=data,
            files=files if files else None,
            timeout=60  # Longer timeout for file processing
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"Backend API call successful - Status: {response.status_code}")
        return result
        
    except requests.exceptions.ConnectionError:
        logger.error("Connection error: Backend unreachable")
        st.error("""❌ **Cannot connect to backend server.**

**Troubleshooting:**
1. Ensure the FastAPI server is running on port 8000
2. Start the backend with: `cd backend && uvicorn main:app --reload`
3. Check if port 8000 is available

**Need help?** See the README.md for detailed setup instructions.""")
        return None
        
    except requests.exceptions.Timeout:
        logger.error("Request timeout")
        st.error("""⏱️ **Request timed out.**

The server took too long to respond (>30 seconds).

**Possible causes:**
- OpenAI API is slow or rate-limited
- Network connectivity issues
- Server is processing a complex query

Please try again in a moment.""")
        return None
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e.response.status_code}")
        try:
            error_detail = e.response.json().get("error", "Unknown error")
            st.error(f"""❌ **Server Error ({e.response.status_code})**

{error_detail}

**Common issues:**
- **503**: Check your OpenAI API key in the `.env` file
- **400**: Message validation failed
- **500**: Internal server error - check backend logs""")
        except:
            st.error(f"""❌ **Server Error ({e.response.status_code})**

An error occurred on the server. Please check the backend logs and try again.""")
        return None
        
    except requests.exceptions.JSONDecodeError:
        logger.error("JSON decode error")
        st.error("""❌ **Invalid response from server.**

Received malformed data from the backend. This might indicate:
- Server configuration issue
- Unexpected error format

Please check the backend logs for details.""")
        return None
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        st.error(f"""❌ **Unexpected error occurred.**

{str(e)}

Please try again or contact support if the issue persists.""")
        return None


def validate_message(message: str) -> bool:
    """
    Validate user message.
    
    Args:
        message: The user's message
        
    Returns:
        True if valid, False otherwise
    """
    if not message or not message.strip():
        st.warning("⚠️ Please enter a message before sending.")
        return False
    
    if len(message) > MAX_MESSAGE_LENGTH:
        st.warning(f"⚠️ Message too long. Maximum {MAX_MESSAGE_LENGTH} characters allowed. Current: {len(message)} characters.")
        return False
    
    return True


def calculate_conversation_stats(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Calculate conversation statistics.
    
    Args:
        messages: List of conversation messages
        
    Returns:
        Dictionary with statistics
    """
    # Filter out welcome message
    actual_messages = [
        msg for msg in messages
        if not (msg["role"] == "assistant" and "Welcome to the Marketing Analytics Copilot" in msg["content"])
    ]
    
    user_messages = [m for m in actual_messages if m["role"] == "user"]
    assistant_messages = [m for m in actual_messages if m["role"] == "assistant"]
    
    # Estimate tokens (rough: 1 token ≈ 4 characters)
    total_chars = sum(len(m["content"]) for m in actual_messages)
    estimated_tokens = total_chars // 4
    
    return {
        "total_messages": len(actual_messages),
        "user_messages": len(user_messages),
        "assistant_messages": len(assistant_messages),
        "estimated_tokens": estimated_tokens
    }


def export_conversation(messages: List[Dict[str, str]]) -> str:
    """
    Export conversation to JSON string.
    
    Args:
        messages: List of conversation messages
        
    Returns:
        JSON string of exported conversation
    """
    # Filter out welcome message
    export_messages = [
        msg for msg in messages
        if not (msg["role"] == "assistant" and "Welcome to the Marketing Analytics Copilot" in msg["content"])
    ]
    
    stats = calculate_conversation_stats(messages)
    
    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "conversation_id": str(uuid.uuid4()),
        "metadata": {
            "message_count": stats["total_messages"],
            "user_messages": stats["user_messages"],
            "assistant_messages": stats["assistant_messages"],
            "estimated_tokens": stats["estimated_tokens"]
        },
        "messages": [
            {
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            for msg in export_messages
        ]
    }
    
    return json.dumps(export_data, indent=2)


def validate_import_data(data: dict) -> tuple:
    """
    Validate imported conversation data.
    
    Args:
        data: Parsed JSON data
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    required_fields = ["version", "messages"]
    
    if not all(field in data for field in required_fields):
        return False, "Missing required fields (version, messages)"
    
    if not isinstance(data["messages"], list):
        return False, "Messages must be a list"
    
    if len(data["messages"]) == 0:
        return False, "No messages found in file"
    
    for i, msg in enumerate(data["messages"]):
        if "role" not in msg or "content" not in msg:
            return False, f"Invalid message format at index {i}"
        if msg["role"] not in ["user", "assistant"]:
            return False, f"Invalid role '{msg['role']}' at index {i}"
    
    return True, "Valid"


def import_conversation(uploaded_file) -> bool:
    """
    Import conversation from JSON file.
    
    Args:
        uploaded_file: Streamlit UploadedFile object
        
    Returns:
        True if successful, False otherwise
    """
    try:
        data = json.loads(uploaded_file.getvalue())
        is_valid, error_msg = validate_import_data(data)
        
        if not is_valid:
            st.error(f"❌ Invalid conversation file: {error_msg}")
            return False
        
        # Add welcome message first
        imported_messages = [
            {
                "role": "assistant",
                "content": """👋 **Conversation Restored!**

This conversation was imported from a saved file. You can continue where you left off.

How can I assist you today?"""
            }
        ]
        
        # Add imported messages
        for msg in data["messages"]:
            imported_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # Load messages into session state
        st.session_state.messages = imported_messages
        st.success(f"✅ Imported {len(data['messages'])} messages successfully!")
        logger.info(f"Conversation imported - {len(data['messages'])} messages")
        return True
        
    except json.JSONDecodeError:
        st.error("❌ Invalid JSON file. Please upload a valid conversation export.")
        return False
    except Exception as e:
        st.error(f"❌ Error importing conversation: {str(e)}")
        logger.error(f"Import error: {str(e)}")
        return False


def clear_conversation():
    """Clear conversation history and reset to welcome message."""
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": """👋 **Welcome to the Marketing Analytics Copilot!**

I'm your AI assistant for marketing analytics. I can help you with:

🔍 **Marketing Audits** - Performance reviews, campaign analysis, ROI assessments
📊 **Attribution Analysis** - Channel analysis, customer journey mapping, multi-touch attribution
🎯 **KPI Strategy** - Metric definition, goal setting, performance frameworks
💬 **General Questions** - Marketing advice, best practices, and guidance

**✨ NEW in Sprint 3 Part 2: Advanced Conversation Features!**
- 📝 Automatic summarization for long conversations
- 🔍 Semantic search to find relevant context
- 💾 Export and import conversations
- 🗑️ Clear history with one click

**Sprint 2 Features:**
- Upload GTM configurations (JSON/CSV) for comprehensive audits
- Get detailed reports with Critical Issues, Warnings, and Optimizations
- Powered by Gemini 2.5-flash with massive context window

**How to use:**
1. Upload a file using the sidebar (optional)
2. Ask your question or request an audit
3. Continue the conversation with follow-up questions
4. Manage your conversation using the sidebar tools

How can I assist you today?"""
        }
    ]
    st.session_state.confirm_clear = False
    logger.info("Conversation history cleared")


def display_chat_message(role: str, content: str):
    """
    Display a chat message with appropriate styling.
    
    Args:
        role: Message role (user or assistant)
        content: Message content
    """
    with st.chat_message(role):
        st.markdown(content)


def main():
    """Main application function."""
    # Initialize session state
    initialize_session_state()
    
    # Header
    st.title("📊 Marketing Analytics Copilot")
    st.markdown("**Sprint 2: Analytics Auditor** - *File Upload & GTM Audit Analysis*")
    
    # Sidebar
    with st.sidebar:
        # Conversation Management Section
        st.header("💬 Conversation Management")
        
        # Calculate and display stats
        stats = calculate_conversation_stats(st.session_state.messages)
        
        st.markdown("**📊 Statistics:**")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Messages", stats["total_messages"])
            st.metric("User", stats["user_messages"])
        with col2:
            st.metric("Est. Tokens", f"{stats['estimated_tokens']:,}")
            st.metric("Assistant", stats["assistant_messages"])
        
        st.divider()
        
        # Action buttons
        st.markdown("**🔧 Actions:**")
        
        # Export button
        if stats["total_messages"] > 0:
            export_json = export_conversation(st.session_state.messages)
            st.download_button(
                label="📥 Export Conversation",
                data=export_json,
                file_name=f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                help="Download conversation as JSON file",
                use_container_width=True
            )
        else:
            st.button(
                "📥 Export Conversation",
                disabled=True,
                help="No messages to export",
                use_container_width=True
            )
        
        # Import button
        import_file = st.file_uploader(
            "📤 Import Conversation",
            type=['json'],
            help="Upload a previously exported conversation",
            key="import_uploader"
        )
        
        if import_file:
            if st.button("Load Imported Conversation", use_container_width=True):
                if import_conversation(import_file):
                    st.rerun()
        
        # Clear button with confirmation
        if stats["total_messages"] > 0:
            if "confirm_clear" not in st.session_state:
                st.session_state.confirm_clear = False
            
            if not st.session_state.confirm_clear:
                if st.button("🗑️ Clear History", type="secondary", use_container_width=True):
                    st.session_state.confirm_clear = True
                    st.rerun()
            else:
                st.warning("⚠️ Are you sure? This cannot be undone.")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Yes, Clear", type="primary", use_container_width=True):
                        clear_conversation()
                        st.rerun()
                with col2:
                    if st.button("❌ Cancel", use_container_width=True):
                        st.session_state.confirm_clear = False
                        st.rerun()
        else:
            st.button(
                "🗑️ Clear History",
                disabled=True,
                help="No messages to clear",
                use_container_width=True
            )
        
        st.divider()
        
        # About section
        st.header("ℹ️ About")
        st.markdown("""
**Sprint 3 Part 2** - Advanced Conversation Features

**New Features:**
- 📝 Auto-summarization (>10 msgs)
- 🔍 Semantic search
- 💾 Export/Import conversations
- 🗑️ Clear history

**Sprint 2 Features:**
- ✅ File upload (JSON/CSV)
- ✅ GTM configuration audits
- ✅ Conversation memory
- ✅ Gemini 2.5-flash integration
        """)
        
        st.divider()
        
        st.header("📎 Upload File")
        uploaded_file = st.file_uploader(
            "Upload GTM Configuration",
            type=['json', 'csv'],
            help="Upload a JSON or CSV file for audit analysis (max 10MB)",
            key="file_uploader"
        )
        
        if uploaded_file:
            st.success(f"✅ File loaded: {uploaded_file.name}")
            st.caption(f"Size: {uploaded_file.size / 1024:.1f} KB")
            st.caption(f"Type: {uploaded_file.type}")
        else:
            st.info("💡 Upload a file to enable audit analysis")
        
        st.divider()
        
        st.header("🔧 System Status")
        # Check backend health
        try:
            health_response = requests.get(f"{BACKEND_URL}/", timeout=5)
            if health_response.status_code == 200:
                st.success("✅ Backend: Connected")
            else:
                st.error("❌ Backend: Error")
        except:
            st.error("❌ Backend: Offline")
    
    st.divider()
    
    # Display chat history
    for message in st.session_state.messages:
        display_chat_message(message["role"], message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask me about marketing analytics...", max_chars=MAX_MESSAGE_LENGTH):
        # Validate message
        if not validate_message(prompt):
            return
        
        # Build user message with file info if present
        user_message = prompt
        if uploaded_file:
            user_message += f"\n\n📎 *Attached: {uploaded_file.name}*"
        
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": user_message})
        display_chat_message("user", user_message)
        
        # Get assistant response
        with st.chat_message("assistant"):
            # Show different spinner based on file presence
            spinner_text = "🔍 Analyzing file and generating audit report..." if uploaded_file else "🤔 Analyzing your query..."
            
            with st.spinner(spinner_text):
                # Filter out welcome message from history (it's not part of the conversation)
                filtered_history = [
                    msg for msg in st.session_state.messages[:-1]  # Exclude the just-added user message
                    if not (msg["role"] == "assistant" and "Welcome to the Marketing Analytics Copilot" in msg["content"])
                ]
                
                response_data = call_backend_api(prompt, filtered_history, uploaded_file)
                
                if response_data and response_data.get("status") == "success":
                    response_text = response_data.get("response", "No response received.")
                    st.markdown(response_text)
                    
                    # Add to chat history
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response_text
                    })
                    logger.info("Response added to chat history")
                    
                    # Clear file after successful processing
                    if uploaded_file:
                        st.info("✅ File processed successfully. Upload a new file for another analysis.")
                else:
                    # Error already displayed by call_backend_api
                    logger.warning("Failed to get valid response from backend")
    
    # Footer
    st.divider()
    st.caption("Marketing Analytics Copilot v2.0.0 | Sprint 3 Part 2: Advanced Conversations | Powered by LangChain & Gemini")


if __name__ == "__main__":
    logger.info("Starting Streamlit application")
    main()

# Made with Bob
