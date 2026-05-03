# 📊 Marketing Analytics Copilot

An AI-powered assistant designed for marketing data engineers and analytics consultants. The Marketing Analytics Copilot leverages Google's Gemini 2.5-flash and LangChain to provide intelligent conversational support, automated Google Tag Manager (GTM) audits, and deep context management.

## ✨ Key Features

* **Intelligent Orchestration:** Automatically routes user queries into specific domains (General, Audit, Attribution, KPI Strategy) using an AI router.
* **GTM Analytics Auditor:** Upload GTM configuration files (JSON/CSV) for automated analysis, surfacing Critical Issues, Warnings, and Optimizations.
* **Advanced Conversational Memory:** 
  * Seamless multi-turn conversations.
  * Automatic background summarization for long chat histories (triggers after 10 messages) to save tokens and maintain performance.
  * Semantic search via Google Embeddings to pull relevant historical context into the active prompt.
* **Session Management:** Export chats to JSON, import historical conversations, and safely clear history with UI protections.
* **Optimized File Handling:** Smart frontend caching prevents redundant file uploads during follow-up questions, saving bandwidth and API costs.

## 🛠️ Tech Stack

* **Frontend:** Streamlit
* **Backend:** FastAPI, Uvicorn
* **AI & Orchestration:** LangChain, Google Generative AI (Gemini 2.5-flash)
* **Embeddings:** Google Generative AI Embeddings

## 🚀 Getting Started

### Prerequisites
* Python 3.9+
* A valid Google Gemini API Key

### Installation

1. **Clone the repository:**
    ```bash
   git clone [https://github.com/yourusername/marketing-analytics-copilot.git](https://github.com/yourusername/marketing-analytics-copilot.git)
   cd marketing-analytics-copilot
'''
2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv     
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Environment Setup:**
   Create a .env file in the root directory and add your Gemini API key:
   ```.env
   GOOGLE_API_KEY=your_gemini_api_key_here
   ```
### Running the Application
To avoid common Windows port-conflict issues, the backend is configured to run on port 8001. You will need two separate terminal windows to run the full stack.
**Terminal 1: Start the FastAPI Backend**
```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8001
```
**Terminal 2: Start the Streamlit Frontend**
```bash
cd frontend
streamlit run app.py
```
The UI will automatically open in your default browser at http://localhost:8501.

##📂 Project Structure
```Structure
├── app.py                      # Streamlit frontend UI and session state
├── main.py                     # FastAPI application, routing, and error handling
├── orchestrator.py             # LangChain master orchestrator and system prompts
├── conversation_manager.py     # Summarization, token estimation, and semantic search
├── auditor_agent.py            # Specialized agent for parsing and analyzing GTM files
├── .env                        # Environment variables (API keys)
└── README.md                   # Project documentation
```
##🧪 Testing & Resilience
The application includes robust error handling and UI protections engineered during Sprint 3:

Validation: Safely rejects invalid JSON/CSV uploads and malformed chat imports.

Graceful Degradation: Continues functioning smoothly even if the embedding model fails or if summarization thresholds are not met.

Domain Restriction Guardrails: The Master Orchestrator is strictly prompt-engineered to politely refuse off-topic requests (e.g., creative writing or non-marketing queries) to protect API costs and maintain professional focus.

Zombie-Server Bypass: Architecture defaults to port 8001 to prevent Uvicorn background-process conflicts.
