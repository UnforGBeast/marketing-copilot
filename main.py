"""
FastAPI Backend for Marketing Analytics Copilot.

This module provides the REST API interface for the frontend,
handling CORS, request validation, and orchestrator integration.
"""
import sys
import json
import logging
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
import os
from dotenv import load_dotenv

from orchestrator import process_query, OrchestratorError, get_orchestrator

# Load environment variables
load_dotenv()

# Setup logger - Configure root logger first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Get logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize FastAPI app
app = FastAPI(
    title="Marketing Analytics Copilot API",
    description="Backend API for Marketing Analytics Copilot - Sprint 2: Analytics Auditor",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("FastAPI application initialized successfully")


# Pydantic models
class QueryRequest(BaseModel):
    """Request model for chat queries."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's message to the copilot"
    )
    
    @field_validator('message')
    def validate_message(cls, v):
        """Validate message is not just whitespace."""
        if not v.strip():
            raise ValueError("Message cannot be empty or whitespace")
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "What are the key marketing KPIs I should track?"
            }
        }


class QueryResponse(BaseModel):
    """Response model for chat queries."""
    response: str = Field(..., description="Orchestrator's response")
    status: str = Field(default="success", description="Response status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "response": "Intent: KPI Strategy\n\nThis query is about defining key performance indicators...",
                "status": "success"
            }
        }


class ErrorResponse(BaseModel):
    """Response model for errors."""
    error: str = Field(..., description="Error message")
    status: str = Field(default="error", description="Error status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "AI service temporarily unavailable",
                "status": "error"
            }
        }


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Override FastAPI's default 422 validation error.
    Returns a clean HTTP 400 Bad Request to match our Test Case 1.02.
    """
    # Extract the custom error message we wrote in the Pydantic validator
    errors = exc.errors()
    error_msg = errors[0].get("msg", "Invalid request format") if errors else "Invalid request format"
    
    # Clean up the "Value error, " prefix that Pydantic v2 automatically adds
    if error_msg.startswith("Value error, "):
        error_msg = error_msg.replace("Value error, ", "")

    logger.warning(f"Validation error: {error_msg}")
    
    return JSONResponse(
        status_code=400,
        content={"error": error_msg, "status": "error"}
    )
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handle HTTP exceptions.
    
    Args:
        request: The incoming request
        exc: The HTTP exception
        
    Returns:
        JSON response with error details
    """
    logger.error(f"HTTP error: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": "error"}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Handle unexpected exceptions.
    
    Args:
        request: The incoming request
        exc: The exception
        
    Returns:
        JSON response with generic error message
    """
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status": "error"}
    )


# Routes
@app.get("/", tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        Dictionary with service status
    """
    logger.info("Health check endpoint called")
    return {
        "status": "healthy",
        "service": "Marketing Analytics Copilot API",
        "version": "1.0.0",
        "sprint": "Sprint 1: Walking Skeleton"
    }


@app.post(
    "/chat",
    response_model=QueryResponse,
    responses={
        200: {"model": QueryResponse, "description": "Successful response"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    tags=["Chat"]
)
async def chat_endpoint(
    message: str = Form(..., min_length=1, max_length=2000),
    file: Optional[UploadFile] = File(None),
    chat_history: str = Form("[]")
):
    """
    Process a chat message with optional file upload, conversation history, and return the orchestrator's response.
    
    This endpoint accepts:
    - A user message (required)
    - An optional file upload (JSON or CSV) for audit analysis
    - Chat history as JSON string for conversation context
    
    The orchestrator will route to specialized agents based on intent and file presence.
    
    Args:
        message: User's text message (form field)
        file: Optional uploaded file (JSON or CSV)
        chat_history: JSON string of previous conversation messages
        
    Returns:
        QueryResponse with the orchestrator's response
        
    Raises:
        HTTPException: If processing fails
    """
    logger.info(f"POST /chat - Message: {len(message)} chars, File: {file.filename if file else 'None'}")
    logger.debug(f"Message preview: {message[:50]}...")
    
    # Validate message
    if not message or not message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty or whitespace"
        )
    
    # Parse chat history
    parsed_history = []
    print(f"\n--- DEBUG TC-3.02 ---")
    print(f"RECEIVED HISTORY PAYLOAD: {chat_history}")
    print(f"---------------------\n")
    
    if chat_history and chat_history != "[]":
        try:
            parsed_history = json.loads(chat_history)
            logger.info(f"Chat history parsed - {len(parsed_history)} messages")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse chat history: {str(e)}")
            parsed_history = []  # Default to empty on error
    
    file_content = None
    file_type = None
    
    # Process file if uploaded
    if file:
        logger.info(f"Processing uploaded file: {file.filename}")
        
        # Validate file type
        if not file.filename.endswith(('.json', '.csv')):
            raise HTTPException(
                status_code=400,
                detail="Only JSON and CSV files are supported. Please upload a .json or .csv file."
            )
        '''
        # Check file size (10MB limit)
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        if file_size > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file_size / 1024 / 1024:.1f}MB). Maximum size is 10MB."
            )
        
        # Read and decode file
        try:
            content_bytes = await file.read()
            file_content = content_bytes.decode('utf-8')
            file_type = 'json' if file.filename.endswith('.json') else 'csv'
            logger.info(f"File decoded successfully - Type: {file_type}, Size: {len(file_content)} chars")
        except UnicodeDecodeError:
            logger.error("File decoding failed - not UTF-8")
            raise HTTPException(
                status_code=400,
                detail="File must be UTF-8 encoded. Please save your file with UTF-8 encoding and try again."
            )
        
        except Exception as e:
            logger.error(f"File read error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read file: {str(e)}"
            )
            '''
        try:
            content_bytes = await file.read()
            
            # Check file size AFTER reading into memory
            file_size = len(content_bytes)
            
            # 🚨 NEW: Empty file check
            if file_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail="The uploaded file is empty. Please check the file and upload again."
                )
                
            # Check for max size (10MB limit)
            if file_size > 10 * 1024 * 1024:  
                raise HTTPException(
                    status_code=400,
                    detail=f"File too large ({file_size / 1024 / 1024:.1f}MB). Maximum size is 10MB."
                )
            
            file_content = content_bytes.decode('utf-8')
            file_type = 'json' if file.filename.endswith('.json') else 'csv'
            logger.info(f"File decoded successfully - Type: {file_type}, Size: {len(file_content)} chars")
            
        except UnicodeDecodeError:
            logger.error("File decoding failed - not UTF-8")
            raise HTTPException(
                status_code=400,
                detail="File must be UTF-8 encoded. Please save your file with UTF-8 encoding and try again."
            )
        except Exception as e:
            logger.error(f"File read error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read file: {str(e)}"
            )
        
    
    # Process query through orchestrator with conversation history
    try:
        response = await process_query(
            message.strip(),
            file_content,
            file_type,
            parsed_history
        )
        
        logger.info("POST /chat - Response generated successfully")
        return QueryResponse(response=response, status="success")
        
    except OrchestratorError as e:
        logger.error(f"Orchestrator error: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="AI service temporarily unavailable. Please check your API key configuration and try again."
        )
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )

@app.on_event("startup")
async def startup_event():
    """Log startup event and initialize AI services."""
    logger.info("=" * 60)
    logger.info("Marketing Analytics Copilot API - Starting Up")
    logger.info("Sprint 2: Analytics Auditor")
    logger.info("=" * 60)
    
    # Force the AI Orchestrator to initialize immediately.
    try:
        logger.info("Verifying AI Orchestrator configuration...")
        get_orchestrator()
        logger.info("AI Orchestrator verified successfully.")
    except OrchestratorError as e:
        logger.critical(f"FATAL STARTUP ERROR: {str(e)}")
        # Explicitly crash the server because it cannot function without the AI
        sys.exit(1)
'''
@app.on_event("startup")
async def startup_event():
    """Log startup event."""
    logger.info("=" * 60)
    logger.info("Marketing Analytics Copilot API - Starting Up")
    logger.info("Sprint 1: Walking Skeleton")
    logger.info("=" * 60)
'''

@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event."""
    logger.info("=" * 60)
    logger.info("Marketing Analytics Copilot API - Shutting Down")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server on http://localhost:8000")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

# Made with Bob
