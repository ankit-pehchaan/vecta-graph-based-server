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
    """AI-generated intelligence summary."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["intelligence_summary"] = "intelligence_summary"
    summary: str
    insights: list[str] = []
    timestamp: Optional[str] = None


class SuggestedNextSteps(BaseModel):
    """AI-generated suggested next steps."""
    model_config = ConfigDict(extra='ignore')
    
    type: Literal["suggested_next_steps"] = "suggested_next_steps"
    steps: list[str] = []
    priority: Optional[str] = None  # High, Medium, Low
    timestamp: Optional[str] = None


class WSMessage(BaseModel):
    """Union type for all WebSocket messages."""
    model_config = ConfigDict(extra='ignore')
    
    # This is a base class - actual messages will be one of the above types
    pass

