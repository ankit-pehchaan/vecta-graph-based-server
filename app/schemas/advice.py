from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.financial import FinancialProfile

#
# Core WebSocket messages
#


class UserMessage(BaseModel):
    """Message sent by user to agent."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["user_message"] = "user_message"
    content: str
    timestamp: Optional[str] = None


class AgentResponse(BaseModel):
    """Agent response chunk (streaming)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["agent_response"] = "agent_response"
    content: str
    is_complete: bool = False
    timestamp: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Real-time profile update as facts are extracted."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["profile_update"] = "profile_update"
    profile: FinancialProfile
    changes: Optional[dict] = None
    timestamp: Optional[str] = None


class Greeting(BaseModel):
    """Initial greeting message."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["greeting"] = "greeting"
    message: str
    is_first_time: bool
    timestamp: Optional[str] = None


class ErrorMessage(BaseModel):
    """Error message."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None
    timestamp: Optional[str] = None


class IntelligenceSummary(BaseModel):
    """AI-generated intelligence summary (streaming). Feature-flagged."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["intelligence_summary"] = "intelligence_summary"
    content: str
    is_complete: bool = False
    summary: Optional[str] = None
    insights: list[str] = []
    timestamp: Optional[str] = None


#
# UI actions (server -> client)
#


class UIAction(BaseModel):
    """A clickable UI action (quick reply / CTA)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    action_type: Literal["send_message", "open_url", "noop"] = "send_message"
    message: Optional[str] = None
    url: Optional[str] = None
    style: Optional[Literal["primary", "secondary", "ghost"]] = "secondary"
    disabled: bool = False


class UIActionsMessage(BaseModel):
    """A set of actions to render in the chat UI."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["ui_actions"] = "ui_actions"
    actions: list[UIAction] = []
    hint: Optional[str] = None
    ephemeral: bool = True
    timestamp: Optional[str] = None


#
# Document processing messages
#


class DocumentUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["document_upload"] = "document_upload"
    s3_url: str
    document_type: str
    filename: str
    timestamp: Optional[str] = None


class DocumentProcessing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["document_processing"] = "document_processing"
    status: str
    message: str
    timestamp: Optional[str] = None


class DocumentExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["document_extraction"] = "document_extraction"
    extraction_id: str
    summary: str
    extracted_data: dict
    document_type: str
    requires_confirmation: bool = True
    timestamp: Optional[str] = None


class DocumentConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["document_confirm"] = "document_confirm"
    extraction_id: str
    confirmed: bool
    corrections: Optional[dict] = None
    timestamp: Optional[str] = None


#
# Visualization cards (server -> client)
#


class VizPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: Any
    y: float


class VizSeries(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    data: list[VizPoint]


class VizChart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["line", "bar", "area"]
    x_label: str
    y_label: str
    x_unit: Optional[str] = None
    y_unit: Optional[str] = None


class VizTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    columns: list[str] = []
    rows: list[list[Any]] = []


class VizScorecardKpi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    value: Any
    note: Optional[str] = None


class VizScorecard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kpis: list[VizScorecardKpi] = []


class VizTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    detail: Optional[str] = None


class VizTimeline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[VizTimelineEvent] = []


class VisualizationMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["visualization"] = "visualization"
    spec_version: Literal["1"] = "1"

    viz_id: str
    title: str
    subtitle: Optional[str] = None
    narrative: Optional[str] = None

    chart: Optional[VizChart] = None
    series: list[VizSeries] = []
    table: Optional[VizTable] = None
    scorecard: Optional[VizScorecard] = None
    timeline: Optional[VizTimeline] = None

    explore_next: list[str] = []
    assumptions: list[str] = []
    meta: dict[str, Any] = {}


class WSMessage(BaseModel):
    """Union base for all WS messages."""

    model_config = ConfigDict(extra="ignore")

    pass


