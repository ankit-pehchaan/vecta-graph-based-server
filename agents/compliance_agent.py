"""
ComplianceAgent - Output filter to ensure regulatory compliance.

This agent reviews EVERY response before it goes to the user to ensure:
- No financial advice language
- Neutral, educational tone
- Facts and scenarios only
- No product recommendations
"""

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


class ComplianceResponse(BaseModel):
    """
    Structured response from ComplianceAgent.
    """
    approved: bool | None = Field(
        default=None,
        description="Is the response compliant and safe to send?"
    )
    compliant_response: str | None = Field(
        default=None,
        description="The response to send (original if approved, rewritten if needed)"
    )
    violations_found: list[str] | None = Field(
        default=None,
        description="List of compliance issues found (for logging)"
    )
    changes_made: list[str] | None = Field(
        default=None,
        description="List of changes made to the response (if any)"
    )
    reasoning: str | None = Field(
        default=None,
        description="Explanation of compliance check"
    )


class ComplianceAgent:
    """
    Agent that filters all responses for regulatory compliance.
    
    This agent:
    - Reviews every response before sending to user
    - Checks for advice-language violations
    - Rewrites non-compliant responses
    - Maintains educational, neutral tone
    """
    
    def __init__(self, model_id: str | None = None):
        """Initialize ComplianceAgent with model."""
        self.model_id = model_id or Config.MODEL_ID
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "compliance_agent_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template
    
    def _ensure_agent(self, instructions: str) -> Agent:
        """Ensure a single agent instance is reused for performance."""
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=ComplianceResponse,
                markdown=False,
                debug_mode=False,  # Less verbose for compliance checks
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent
    
    def review(
        self,
        response_text: str,
        response_type: str = "conversation",
        context_summary: str | None = None,
    ) -> ComplianceResponse:
        """
        Review a response for compliance before sending to user.
        
        Args:
            response_text: The response to review
            response_type: Type of response (conversation, summary, visualization_intro)
            context_summary: Brief context for compliance check
        
        Returns:
            ComplianceResponse with approved status and compliant response
        """
        prompt_template = self._load_prompt()
        
        prompt = prompt_template.format(
            response_text=response_text,
            response_type=response_type,
            context_summary=context_summary or "General conversation",
        )
        
        agent = self._ensure_agent(prompt)
        
        response = agent.run(
            "Review this response for compliance. "
            "If it violates any rules, rewrite it to be compliant while preserving the intent."
        ).content
        
        return response
    
    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None

