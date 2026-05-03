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
