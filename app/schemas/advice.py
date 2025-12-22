from pydantic import BaseModel, ConfigDict
from typing import Optional, Literal
from app.schemas.financial import FinancialProfile


class UserMessage(BaseModel):
    """Message sent by user to agent."""
    model_config = ConfigDict(extra='forbid')
    
    type: Literal["user_message"] = "user_message"
    content: str
    timestamp: Optional[str] = None


class AgentResponse(BaseModel):
    """Agent response chunk (streaming)."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["agent_response"] = "agent_response"
    content: str  # Chunk of response
    is_complete: bool = False  # True when this is the final chunk
    timestamp: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Real-time profile update as facts are extracted."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["profile_update"] = "profile_update"
    profile: FinancialProfile
    changes: Optional[dict] = None  # What changed in this update
    timestamp: Optional[str] = None


class Greeting(BaseModel):
    """Initial greeting message."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["greeting"] = "greeting"
    message: str
    is_first_time: bool
    timestamp: Optional[str] = None


class ErrorMessage(BaseModel):
    """Error message."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None
    timestamp: Optional[str] = None


class IntelligenceSummary(BaseModel):
    """AI-generated intelligence summary (streaming)."""
    model_config = ConfigDict(extra='ignore')

    type: Literal["intelligence_summary"] = "intelligence_summary"
    content: str  # Chunk of content when streaming
    is_complete: bool = False  # True when this is the final chunk
    summary: Optional[str] = None  # Full summary (for non-streaming/final)
    insights: list[str] = []
    timestamp: Optional[str] = None


# Document processing messages

class DocumentUploadPrompt(BaseModel):
    """
    Server-initiated prompt to trigger document upload widget in UI.

    Sent when the agent detects user wants to upload a document.
    The frontend should display an inline upload widget when receiving this.
    """
    model_config = ConfigDict(extra='ignore')

    type: Literal["document_upload_prompt"] = "document_upload_prompt"
    message: str  # Agent's response acknowledging the upload request
    suggested_types: list[str] = []  # Suggested document types based on context
    timestamp: Optional[str] = None


class DocumentUpload(BaseModel):
    """Document upload request from client."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["document_upload"] = "document_upload"
    s3_url: str
    document_type: str  # "bank_statement", "tax_return", "investment_statement", "payslip"
    filename: str
    timestamp: Optional[str] = None


class DocumentProcessing(BaseModel):
    """Status update during document processing."""
    model_config = ConfigDict(extra='ignore')

    type: Literal["document_processing"] = "document_processing"
    status: str  # "downloading", "parsing", "analyzing", "complete", "error"
    message: str
    timestamp: Optional[str] = None


class DocumentExtraction(BaseModel):
    """Extraction result sent for user confirmation."""
    model_config = ConfigDict(extra='ignore')

    type: Literal["document_extraction"] = "document_extraction"
    extraction_id: str  # UUID to track this extraction
    summary: str  # Human-readable summary for chat
    extracted_data: dict  # ProfileExtractionResult as dict
    document_type: str
    requires_confirmation: bool = True
    timestamp: Optional[str] = None


class DocumentConfirm(BaseModel):
    """User confirmation/rejection of extracted data."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["document_confirm"] = "document_confirm"
    extraction_id: str
    confirmed: bool
    corrections: Optional[dict] = None  # User corrections if any
    timestamp: Optional[str] = None


class PipelineDebug(BaseModel):
    """
    Debug information from the education pipeline.

    Sent after each message to provide visibility into pipeline stages:
    1. Intent Classification - What user is trying to do
    2. Validation - Profile completeness check
    3. Strategy - Decided conversation direction
    4. Output QA - Response quality review
    """
    model_config = ConfigDict(extra='ignore')

    type: Literal["pipeline_debug"] = "pipeline_debug"
    intent: dict  # IntentClassification result
    validation: dict  # ValidationResult
    strategy: dict  # StrategyDecision
    qa_result: dict  # OutputQAResult
    duration_seconds: float
    timestamp: Optional[str] = None


class WSMessage(BaseModel):
    """Union type for all WebSocket messages."""
    model_config = ConfigDict(extra='ignore')

    # This is a base class - actual messages will be one of the above types
    pass

