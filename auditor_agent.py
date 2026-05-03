"""
Analytics Auditor Agent for Marketing Analytics Copilot.

This module provides specialized analysis of GTM (Google Tag Manager)
configurations, identifying issues, optimizations, and best practices.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

# Load environment variables
load_dotenv()

# Setup logger
logger = logging.getLogger(__name__)


class AuditorError(Exception):
    """Custom exception for auditor errors."""
    pass


class AnalyticsAuditor:
    """
    Specialized agent for auditing marketing analytics configurations.
    
    This agent analyzes GTM configurations (JSON/CSV) and provides
    structured audit reports with critical issues, warnings, and
    optimization recommendations.
    
    Attributes:
        llm: ChatGoogleGenerativeAI instance for analysis
        system_prompt: System prompt for audit analysis
    """
    
    def __init__(self):
        """Initialize the Analytics Auditor with Gemini 2.5-flash."""
        api_key = os.getenv("GOOGLE_API_KEY")
        
        if not api_key or api_key == "your_google_api_key_here":
            logger.error("GOOGLE_API_KEY not found or not configured in environment")
            raise AuditorError("Google API key not configured. Please set GOOGLE_API_KEY in .env file")
        
        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.0,  # Deterministic for audits
                api_key=api_key
            )
            logger.info("Analytics Auditor initialized successfully with gemini-2.5-flash")
        except Exception as e:
            logger.error(f"Failed to initialize Analytics Auditor: {str(e)}")
            raise AuditorError(f"Auditor initialization failed: {str(e)}")
        
        self.system_prompt = self._create_system_prompt()
    
    def _create_system_prompt(self) -> str:
        """
        Create the system prompt for GTM configuration audits.
        
        Returns:
            System prompt string for the Analytics Auditor
        """
        return """You are a Senior MarTech QA Engineer specializing in Google Tag Manager (GTM) audits and marketing analytics configuration reviews.

Your expertise includes:
- Google Tag Manager (GTM) container analysis
- Tag, trigger, and variable configuration validation
- Data layer implementation review
- Tracking code quality assessment
- Marketing analytics best practices
- Privacy and compliance (GDPR, CCPA)
- Performance optimization

**Your Task:**
Analyze the provided tracking configuration file (JSON or CSV format) and provide a comprehensive audit report.

**Focus Areas:**
1. **Critical Issues** - Problems that break tracking or cause data loss
   - Missing or incomplete triggers
   - Broken variable references
   - Invalid tag configurations
   - Security vulnerabilities (exposed API keys, PII in URLs)
   - Consent management issues

2. **Warnings** - Issues that may cause problems or inconsistencies
   - Duplicate tags or variables
   - Naming convention violations
   - Deprecated tag types
   - Missing error handling
   - Suboptimal trigger conditions

3. **Optimizations** - Improvements and best practices
   - Performance enhancements (tag sequencing, async loading)
   - Code consolidation opportunities
   - Better naming conventions
   - Enhanced error tracking
   - Documentation improvements

**Output Format (Strict Markdown):**

# 📊 GTM Configuration Audit Report

## Executive Summary
[2-3 sentence overview of the configuration health and key findings]

---

## 🔴 Critical Issues
[List each critical issue with:
- **Issue:** Clear description
- **Impact:** What breaks or fails
- **Location:** Where in the config (tag name, variable, etc.)
- **Fix:** Specific remediation steps]

---

## ⚠️ Warnings
[List each warning with:
- **Issue:** Clear description
- **Risk:** Potential problems
- **Location:** Where in the config
- **Recommendation:** How to address]

---

## 💡 Optimizations
[List each optimization with:
- **Opportunity:** What can be improved
- **Benefit:** Expected improvement
- **Implementation:** How to implement]

---

## ✅ Summary & Priorities

### Overall Health Score
[Rate the configuration: Excellent / Good / Fair / Poor]

### Priority Actions
1. [Most critical action]
2. [Second priority]
3. [Third priority]

### Next Steps
[Recommended follow-up actions]

---

**Analysis Guidelines:**
- Be specific with tag names, variable names, and line numbers when possible
- Provide actionable recommendations, not just observations
- Consider both technical correctness and business impact
- Flag any privacy/compliance concerns immediately
- Suggest concrete code examples for fixes when relevant
- If the file format is unclear or corrupted, state that clearly

**Important:** If the uploaded file doesn't appear to be a GTM configuration or tracking setup, politely explain what you expected and ask for clarification."""
    
    async def analyze_configuration(
        self,
        user_query: str,
        file_content: str,
        file_type: str
    ) -> str:
        """
        Analyze a GTM configuration file and return a structured audit report.
        
        Args:
            user_query: The user's audit request/question
            file_content: The decoded file content as a string
            file_type: File type ('json' or 'csv')
            
        Returns:
            Structured Markdown audit report
            
        Raises:
            AuditorError: If analysis fails
        """
        # Validate inputs
        if not file_content or not file_content.strip():
            logger.warning("Empty file content received")
            raise AuditorError("File content cannot be empty")
        
        if file_type not in ['json', 'csv']:
            logger.warning(f"Invalid file type: {file_type}")
            raise AuditorError(f"Unsupported file type: {file_type}. Only JSON and CSV are supported.")
        
        logger.info(f"Analyzing {file_type.upper()} configuration - Length: {len(file_content)} chars")
        logger.debug(f"User query: {user_query[:100]}...")
        
        try:
            # Construct the analysis prompt
            analysis_prompt = f"""**User Request:** {user_query}

**File Type:** {file_type.upper()}

**Configuration Content:**
```{file_type}
{file_content}
```

Please analyze this configuration and provide a comprehensive audit report following the specified format."""
            
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=analysis_prompt)
            ]
            
            logger.debug("Sending configuration to Gemini for analysis")
            response = await self.llm.ainvoke(messages)
            
            result = response.content
            logger.info(f"Audit report generated successfully - Length: {len(result)} chars")
            logger.debug(f"Report preview: {result[:200]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing configuration: {str(e)}", exc_info=True)
            raise AuditorError(f"Failed to analyze configuration: {str(e)}")
    
    async def quick_validation(self, file_content: str, file_type: str) -> dict:
        """
        Perform quick validation of file format and structure.
        
        Args:
            file_content: The decoded file content
            file_type: File type ('json' or 'csv')
            
        Returns:
            Dictionary with validation results
        """
        validation = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "file_size": len(file_content),
            "line_count": len(file_content.split('\n'))
        }
        
        try:
            if file_type == 'json':
                import json
                json.loads(file_content)
                logger.info("JSON validation passed")
            elif file_type == 'csv':
                import csv
                import io
                csv.reader(io.StringIO(file_content))
                logger.info("CSV validation passed")
        except json.JSONDecodeError as e:
            validation["is_valid"] = False
            validation["errors"].append(f"Invalid JSON format: {str(e)}")
            logger.error(f"JSON validation failed: {str(e)}")
        except csv.Error as e:
            validation["is_valid"] = False
            validation["errors"].append(f"Invalid CSV format: {str(e)}")
            logger.error(f"CSV validation failed: {str(e)}")
        except Exception as e:
            validation["warnings"].append(f"Validation warning: {str(e)}")
            logger.warning(f"Validation warning: {str(e)}")
        
        return validation


# Global auditor instance
_auditor: Optional[AnalyticsAuditor] = None


def get_auditor() -> AnalyticsAuditor:
    """
    Get or create the global auditor instance.
    
    Returns:
        AnalyticsAuditor instance
    """
    global _auditor
    if _auditor is None:
        _auditor = AnalyticsAuditor()
    return _auditor


async def analyze_configuration(
    user_query: str,
    file_content: str,
    file_type: str
) -> str:
    """
    Convenience function to analyze configurations using the global auditor.
    
    Args:
        user_query: The user's audit request
        file_content: The decoded file content
        file_type: File type ('json' or 'csv')
        
    Returns:
        Structured audit report
        
    Raises:
        AuditorError: If analysis fails
    """
    auditor = get_auditor()
    return await auditor.analyze_configuration(user_query, file_content, file_type)

# Made with Bob
