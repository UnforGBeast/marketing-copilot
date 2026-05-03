"""
Conversation Manager for Marketing Analytics Copilot.

This module handles advanced conversation features including:
- Conversation summarization for long histories
- Semantic search using embeddings
- Context optimization for LLM
"""

import logging
from typing import Optional, List, Dict, Any, Union
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
import numpy as np

# Setup logger
logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Manages conversation history, summarization, and semantic search.
    
    Attributes:
        llm: ChatGoogleGenerativeAI instance for summarization
        embeddings: GoogleGenerativeAIEmbeddings for semantic search
        summarization_threshold: Number of messages before summarization
        keep_recent_count: Number of recent messages to keep in full
        message_embeddings: Cache of message embeddings
    """
    
    def __init__(
        self,
        llm: ChatGoogleGenerativeAI,
        summarization_threshold: int = 10,
        keep_recent_count: int = 5
    ):
        """
        Initialize the conversation manager.
        
        Args:
            llm: LangChain LLM instance for summarization
            summarization_threshold: Trigger summarization after this many messages
            keep_recent_count: Keep this many recent messages in full detail
        """
        self.llm = llm
        self.summarization_threshold = summarization_threshold
        self.keep_recent_count = keep_recent_count
        self.message_embeddings: List[Dict[str, Any]] = []
        
        # Initialize embeddings model for semantic search
        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model="models/embedding-001"
            )
            logger.info("Embeddings model initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize embeddings: {str(e)}")
            self.embeddings = None
    
    def should_summarize(self, history: List[Dict[str, str]]) -> bool:
        """
        Check if conversation history should be summarized.
        
        Args:
            history: List of conversation messages
            
        Returns:
            True if history exceeds threshold, False otherwise
        """
        # Don't count system messages or summaries
        user_assistant_messages = [
            msg for msg in history 
            if msg.get("role") in ["user", "assistant"]
        ]
        
        should_summarize = len(user_assistant_messages) > self.summarization_threshold
        
        if should_summarize:
            logger.info(f"Summarization triggered - {len(user_assistant_messages)} messages")
        
        return should_summarize
    
    async def summarize_history(
        self,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Summarize older messages in conversation history.
        
        This method:
        1. Keeps the most recent N messages in full detail
        2. Summarizes all older messages into a concise summary
        3. Returns both the summary and recent messages
        
        Args:
            history: List of conversation messages
            
        Returns:
            Dictionary containing:
                - summary: Concise summary of older messages
                - summarized_count: Number of messages summarized
                - recent_messages: List of recent messages kept in full
        """
        if len(history) <= self.keep_recent_count:
            logger.info("History too short to summarize")
            return {
                "summary": None,
                "summarized_count": 0,
                "recent_messages": history
            }
        
        # Split history into older (to summarize) and recent (keep full)
        messages_to_summarize = history[:-self.keep_recent_count]
        recent_messages = history[-self.keep_recent_count:]
        
        logger.info(f"Summarizing {len(messages_to_summarize)} messages, keeping {len(recent_messages)} recent")
        
        # Build conversation text for summarization
        conversation_text = self._format_messages_for_summary(messages_to_summarize)
        
        # Create summarization prompt
        summarization_prompt = f"""You are summarizing a conversation between a user and a Marketing Analytics Copilot AI assistant.

Your task is to create a concise but comprehensive summary of the conversation below. Focus on:
- Key topics discussed
- Important questions asked by the user
- Main recommendations or insights provided
- Any specific tools, metrics, or strategies mentioned
- Context that would be helpful for continuing the conversation

Keep the summary under 200 words but ensure all important context is preserved.

CONVERSATION TO SUMMARIZE:
{conversation_text}

SUMMARY:"""
        
        try:
            # Generate summary using LLM
            messages = [HumanMessage(content=summarization_prompt)]
            response = await self.llm.ainvoke(messages)
            # Handle response content (can be str or list)
            if isinstance(response.content, str):
                summary = response.content.strip()
            else:
                summary = str(response.content).strip()
            
            logger.info(f"Summary generated - {len(summary)} chars")
            
            return {
                "summary": summary,
                "summarized_count": len(messages_to_summarize),
                "recent_messages": recent_messages
            }
            
        except Exception as e:
            logger.error(f"Summarization failed: {str(e)}")
            # Fallback: return all messages without summarization
            return {
                "summary": None,
                "summarized_count": 0,
                "recent_messages": history
            }
    
    def _format_messages_for_summary(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """
        Format messages into readable text for summarization.
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Formatted conversation text
        """
        formatted = []
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                formatted.append(f"User: {content}")
            elif role == "assistant":
                # Truncate very long assistant responses
                if len(content) > 500:
                    content = content[:500] + "..."
                formatted.append(f"Assistant: {content}")
        
        return "\n\n".join(formatted)
    
    async def prepare_context_with_summary(
        self,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> List[BaseMessage]:
        """
        Prepare optimized context for LLM with summarization.
        
        Args:
            history: Full conversation history
            system_prompt: System prompt for the orchestrator
            
        Returns:
            List of LangChain messages with summary injected
        """
        messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]
        
        # Check if summarization is needed
        if self.should_summarize(history):
            logger.info("📝 Generating conversation summary...")
            summary_result = await self.summarize_history(history)
            
            if summary_result["summary"]:
                logger.info(f"✅ Summary generated: {summary_result['summarized_count']} messages summarized")
                logger.info(f"📊 Keeping {len(summary_result['recent_messages'])} recent messages in full")
                logger.debug(f"Summary preview: {summary_result['summary'][:100]}...")
                
                # Add summary as a system message
                summary_message = SystemMessage(
                    content=f"""CONVERSATION SUMMARY (previous {summary_result['summarized_count']} messages):
{summary_result['summary']}

--- Recent conversation continues below ---"""
                )
                messages.append(summary_message)
                
                # Add recent messages in full
                for msg in summary_result["recent_messages"]:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
            else:
                # Summarization failed, use full history
                for msg in history:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
        else:
            # No summarization needed, use full history
            for msg in history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        return messages
    
    async def add_message_embedding(
        self,
        message: str,
        role: str,
        index: int
    ) -> bool:
        """
        Generate and store embedding for a message.
        
        Args:
            message: Message content
            role: Message role (user/assistant)
            index: Message index in conversation
            
        Returns:
            True if successful, False otherwise
        """
        if not self.embeddings:
            logger.warning("Embeddings not available")
            return False
        
        try:
            # Generate embedding
            embedding = await self.embeddings.aembed_query(message)
            
            # Store embedding with metadata
            self.message_embeddings.append({
                "index": index,
                "role": role,
                "content": message,
                "embedding": np.array(embedding)
            })
            
            logger.debug(f"Embedding added for message {index}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            return False
    
    async def find_relevant_messages(
        self,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Find most relevant past messages using semantic search.
        
        Args:
            query: Current user query
            top_k: Number of relevant messages to return
            min_similarity: Minimum cosine similarity threshold
            
        Returns:
            List of relevant messages with similarity scores
        """
        if not self.embeddings or not self.message_embeddings:
            logger.warning("Semantic search not available")
            return []
        
        try:
            # Generate embedding for query
            query_embedding = await self.embeddings.aembed_query(query)
            query_vector = np.array(query_embedding).reshape(1, -1)
            
            # Calculate similarities using dot product (cosine similarity for normalized vectors)
            similarities = []
            for msg_data in self.message_embeddings:
                msg_vector = msg_data["embedding"].reshape(1, -1)
                # Calculate cosine similarity manually
                similarity = float(np.dot(query_vector, msg_vector.T)[0][0])
                
                if similarity >= min_similarity:
                    similarities.append({
                        "index": msg_data["index"],
                        "role": msg_data["role"],
                        "content": msg_data["content"],
                        "similarity": float(similarity)
                    })
            
            # Sort by similarity and return top K
            similarities.sort(key=lambda x: x["similarity"], reverse=True)
            relevant = similarities[:top_k]
            
            logger.info(f"Found {len(relevant)} relevant messages (threshold: {min_similarity})")
            
            return relevant
            
        except Exception as e:
            logger.error(f"Semantic search failed: {str(e)}")
            return []
    
    def clear_embeddings(self):
        """Clear all stored embeddings."""
        self.message_embeddings = []
        logger.info("Embeddings cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get conversation manager statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "embeddings_count": len(self.message_embeddings),
            "summarization_threshold": self.summarization_threshold,
            "keep_recent_count": self.keep_recent_count,
            "embeddings_available": self.embeddings is not None
        }


# Made with Bob - Sprint 3 Part 2: Conversation Manager