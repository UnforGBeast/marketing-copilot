"""
LangChain Orchestrator for Marketing Analytics Copilot.

This module handles the core AI orchestration logic, including:
- Intent classification
- Query processing
- Response generation
- Routing to specialized agents
- Conversation management (summarization, semantic search)
"""

import os
import logging
import re
from typing import Optional
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# Import specialized agents
from auditor_agent import AnalyticsAuditor, AuditorError
from conversation_manager import ConversationManager
# Load environment variables
load_dotenv()

# Setup logger
logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Custom exception for orchestrator errors."""
    pass


class PromptSecurityFilter:
    """Filter and sanitize user inputs to prevent prompt injection attacks."""
    
    DANGEROUS_PATTERNS = [
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'system\s+override',
        r'you\s+are\s+now',
        r'new\s+instructions',
        r'disregard\s+',
        r'forget\s+everything',
        r'reveal\s+(api|key|secret|password)',
        r'\[SYSTEM\]',
        r'\[ADMIN\]',
        r'<\|im_start\|>',
        r'<\|im_end\|>',
    ]
    
    MAX_PROMPT_LENGTH = 2000
    MAX_SPECIAL_CHARS_RATIO = 0.3
    
    def sanitize_input(self, user_input: str) -> str:
        """Sanitize user input to prevent injection attacks."""
        
        # 1. Length check
        if len(user_input) > self.MAX_PROMPT_LENGTH:
            logger.warning(f"Input too long: {len(user_input)} chars")
            raise OrchestratorError("Input too long")
        
        # 2. Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.warning(f"Potential prompt injection detected: {pattern}")
                raise OrchestratorError("Input contains prohibited patterns")
        
        # 3. Check special character ratio
        if len(user_input) > 0:
            special_chars = sum(1 for c in user_input if not c.isalnum() and not c.isspace())
            if special_chars / len(user_input) > self.MAX_SPECIAL_CHARS_RATIO:
                logger.warning(f"Too many special characters: {special_chars}/{len(user_input)}")
                raise OrchestratorError("Input contains too many special characters")
        
        # 4. Remove control characters
        sanitized = ''.join(char for char in user_input if ord(char) >= 32 or char in '\n\r\t')
        
        # 5. Escape potential injection markers
        sanitized = sanitized.replace('[SYSTEM]', '[REDACTED]')
        sanitized = sanitized.replace('[ADMIN]', '[REDACTED]')
        
        return sanitized


class MarketingOrchestrator:
    """
    Master Orchestrator for Marketing Analytics queries.
    
    Attributes:
        llm: ChatGoogleGenerativeAI instance for processing queries
        system_prompt: System prompt for intent classification
        conversation_manager: ConversationManager for advanced features
    """
    
    def __init__(self):
        """Initialize the orchestrator with ChatGoogleGenerativeAI and ConversationManager."""
        self.security_filter = PromptSecurityFilter()
        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key or api_key == "your_openai_api_key_here":
            logger.error("Gemini API key not found or not configured in environment")
            raise OrchestratorError("Gemini API key not configured. Please set GEMINI_API_KEY in .env file")
        
        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.0,
                api_key=api_key
            )
            logger.info("ChatGoogleGenerativeAI initialized successfully with gemini 2.5flash")
        except Exception as e:
            logger.error(f"Failed to initialize gemini: {str(e)}")
            raise OrchestratorError(f"LLM initialization failed: {str(e)}")
        
        self.system_prompt = self._create_system_prompt()
        
        # Initialize conversation manager for Sprint 3 Part 2 features
        try:
            self.conversation_manager = ConversationManager(
                llm=self.llm,
                summarization_threshold=10,
                keep_recent_count=5
            )
            logger.info("ConversationManager initialized successfully")
        except Exception as e:
            logger.warning(f"ConversationManager initialization failed: {str(e)}")
            self.conversation_manager = None
    
    def _create_system_prompt(self) -> str:
        """
        Create the system prompt for intent classification.
        
        Returns:
            System prompt string for the Master Orchestrator
        """
        return """You are a Master Orchestrator for a Marketing Analytics Copilot.
Your role is to analyze user queries and classify their intent into one of four categories.

Your Instructions:
1. DOMAIN RESTRICTION: You must strictly limit your responses to marketing, web analytics, tracking (GTM/GA4/Pixels), KPI strategy, attribution modeling, and data engineering. 
2. OFF-TOPIC REFUSAL: If the user asks for anything outside this domain (e.g., writing creative fiction, general trivia, unrelated coding, "why apples are red", or writing a sea shanty), you must politely refuse. State that you are a specialized Marketing Analytics Copilot and ask how you can help them with their marketing data.
3. MEMORY: You have conversational memory. Use context from previous messages to answer follow-up questions naturally.
4. TONE & STYLE: Answer within-domain questions directly, clearly, and professionally. Do NOT output "Intent Category" or routing explanations. Keep your responses structured and easy to read using Markdown formatting.


Intent Categories:
1. General: General marketing questions, conversations, greetings, or queries that don't fit other categories
2. Audit: Marketing audit requests, performance reviews, campaign analysis, ROI assessments
3. Attribution: Attribution modeling, channel analysis, customer journey mapping, multi-touch attribution
4. KPI Strategy: KPI definition, metric strategy, goal setting, performance measurement frameworks
Note: 
If the user uploads a GTM file for an audit, the backend will automatically route it to a specialized Auditor Agent, but you are responsible for handling all general chat and follow-ups.
Keep responses concise, structured, and professional. 
Use clear formatting with line breaks between sections."""
    
    def _build_message_history(
        self,
        chat_history: Optional[list],
        user_query: str
    ) -> list:
        """
        Build message history for LLM context with conversation memory.
        
        Args:
            chat_history: List of previous messages with 'role' and 'content'
            user_query: Current user query
            
        Returns:
            List of LangChain message objects
        """
        messages = [SystemMessage(content=self.system_prompt)]
        
        # Inject chat history if provided
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # Add current query
        messages.append(HumanMessage(content=user_query))
        
        logger.debug(f"Built message history: {len(messages)} messages")
        return messages
    
    async def _classify_intent(self, user_query: str) -> str:
        """
        Classify the intent of a user query.
        
        Args:
            user_query: The user's input message
            
        Returns:
            Intent category as a string
        """
        try:
            classification_prompt = f"""Classify this query into ONE category: General, Audit, Attribution, or KPI Strategy.

Query: {user_query}

Respond with ONLY the category name (one word)."""
            
            messages = [
                HumanMessage(content=classification_prompt)
            ]
            
            response = await self.llm.ainvoke(messages)
            intent = str(response.content).strip().lower()
            logger.info(f"Intent classified as: {intent}")
            return intent
            
        except Exception as e:
            logger.error(f"Intent classification error: {str(e)}")
            return "general"  # Default to general on error
    
    async def process_query(
        self,
        user_query: str,
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        chat_history: Optional[list] = None
    ) -> str:
        """
        Process a user query with conversation history and return the orchestrator's response.
        Routes to specialized agents based on intent and available data.
        
        Args:
            user_query: The user's input message
            file_content: Optional file content for analysis
            file_type: Optional file type ('json' or 'csv')
            chat_history: Optional list of previous conversation messages
            
        Returns:
            The orchestrator's response as a string
            
        Raises:
            OrchestratorError: If processing fails
        """
        if not user_query or not user_query.strip():
            logger.warning("Empty query received")
            raise OrchestratorError("Query cannot be empty")
        
        # Sanitize user input to prevent prompt injection
        try:
            sanitized_query = self.security_filter.sanitize_input(user_query)
        except OrchestratorError as e:
            logger.error(f"Input sanitization failed: {str(e)}")
            raise
        
        history_len = len(chat_history) if chat_history else 0
        logger.info(f"Processing query - Length: {len(sanitized_query)} chars, File: {bool(file_content)}, History: {history_len} msgs")
        logger.debug(f"Query content (sanitized): {sanitized_query[:100]}...")
        
        try:
            # If file content is provided, check if this is an audit request
            if file_content and file_type:
                logger.info(f"File provided ({file_type}) - Classifying intent for routing")
                intent = await self._classify_intent(sanitized_query)
                
                if "audit" in intent:
                    logger.info("Routing to Analytics Auditor agent")
                    try:
                        auditor = AnalyticsAuditor()
                        result = await auditor.analyze_configuration(
                            sanitized_query, file_content, file_type
                        )
                        logger.info("Audit analysis completed successfully")
                        return str(result)
                    except AuditorError as e:
                        logger.error(f"Auditor error: {str(e)}")
                        raise OrchestratorError(f"Audit analysis failed: {str(e)}")
                else:
                    logger.warning(f"File provided but intent is '{intent}', not 'audit'")
                    return f"""📎 **File Uploaded but Intent Mismatch**

You uploaded a {file_type.upper()} file, but your query doesn't appear to be an audit request.

**Your Query:** {sanitized_query}
**Detected Intent:** {intent.title()}

**To analyze this file, please:**
1. Rephrase your request to include "audit" or "analyze"
2. Example: "Please audit this GTM configuration" or "Analyze this tracking setup"

**Or, if you want a different type of analysis:**
- Remove the file and ask your question again
- The file will be ignored for non-audit queries"""
            
            # Standard orchestrator flow (no file or non-audit)
            # Use conversation manager for optimized context if available
            if self.conversation_manager and chat_history:
                logger.info("Using ConversationManager for context optimization")
                
                # Check if summarization will be triggered
                if self.conversation_manager.should_summarize(chat_history):
                    logger.info("=" * 60)
                    logger.info("🔄 CONVERSATION SUMMARIZATION TRIGGERED")
                    logger.info(f"Total messages in history: {len(chat_history)}")
                    logger.info(f"Threshold: {self.conversation_manager.summarization_threshold}")
                    logger.info("=" * 60)
                
                messages = await self.conversation_manager.prepare_context_with_summary(
                    chat_history,
                    self.system_prompt
                )
                # Add current query (sanitized)
                messages.append(HumanMessage(content=sanitized_query))
            else:
                # Fallback to basic history injection
                logger.info("Using basic message history (no conversation manager)")
                messages = self._build_message_history(chat_history, sanitized_query)
            
            logger.debug(f"Sending request to Gemini API with {len(messages)} messages")
            response = await self.llm.ainvoke(messages)
            
            result = str(response.content)
            logger.info(f"Response generated successfully - Length: {len(result)} chars")
            logger.debug(f"Response preview: {result[:100]}...")
            
            return result
            
        except OrchestratorError:
            # Re-raise orchestrator errors
            raise
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise OrchestratorError(f"Failed to process query: {str(e)}")


# Global orchestrator instance
_orchestrator: Optional[MarketingOrchestrator] = None


def get_orchestrator() -> MarketingOrchestrator:
    """
    Get or create the global orchestrator instance.
    
    Returns:
        MarketingOrchestrator instance
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MarketingOrchestrator()
    return _orchestrator


async def process_query(
    user_query: str,
    file_content: Optional[str] = None,
    file_type: Optional[str] = None,
    chat_history: Optional[list] = None
) -> str:
    """
    Convenience function to process queries using the global orchestrator.
    
    Args:
        user_query: The user's input message
        file_content: Optional file content for analysis
        file_type: Optional file type ('json' or 'csv')
        chat_history: Optional list of previous conversation messages
        
    Returns:
        The orchestrator's response
        
    Raises:
        OrchestratorError: If processing fails
    """
    orchestrator = get_orchestrator()
    return await orchestrator.process_query(user_query, file_content, file_type, chat_history)

# Made with Bob - Sprint 3 Part 1: Conversation Memory
