import os
import asyncio
from typing import Optional, Dict, Any
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.core.config import settings


class IntelligenceSummaryResult(BaseModel):
    """Structured output for intelligence summary."""
    summary: str
    insights: list[str] = []


class SuggestedNextStepsResult(BaseModel):
    """Structured output for suggested next steps."""
    steps: list[str] = []
    priority: Optional[str] = None


class IntelligenceService:
    """Service for generating intelligence summaries and suggested next steps using Agno agents.
    
    Creates and reuses agents per user for performance (per .cursorrules).
    """
    
    def __init__(self):
        self._intelligence_agents: dict[str, Agent] = {}  # Cache agents per user
        self._next_steps_agents: dict[str, Agent] = {}  # Cache agents per user
        self._db_dir = "tmp/agents"
        
        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)
        
        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    
    async def _get_intelligence_agent(self, username: str) -> Agent:
        """Get or create intelligence summary agent for user."""
        if username in self._intelligence_agents:
            return self._intelligence_agents[username]
        
        db_file = os.path.join(self._db_dir, f"intelligence_{username}.db")
        
        agent = Agent(
            name="Intelligence Analyst",
            model=OpenAIChat(id="gpt-4o"),
            instructions="""You are a financial intelligence analyst. Your role is to analyze financial conversations and profiles to generate concise, actionable insights.

CRITICAL FORMATTING RULES:
- Keep output brief and focused (2-3 sentences for summary, 2-4 insights)
- Use minimal markdown: only use **bold** for emphasis on key terms, *italics* for subtle emphasis
- NO code blocks, headers, lists with markdown syntax, or complex formatting
- Write in plain text with simple bold/italics only
- Use color indicators sparingly (e.g., "High risk" or "Positive trend")

Analyze the conversation and financial profile to identify:
- Key financial patterns and trends
- Potential risks or opportunities
- Asset allocation concerns
- Risk tolerance alignment
- Financial gaps or areas needing attention

Provide a brief summary (2-3 sentences) and 2-4 key insights.
Be specific, professional, and focused on actionable intelligence.""",
            db=SqliteDb(db_file=db_file),
            user_id=f"{username}_intelligence",
            output_schema=IntelligenceSummaryResult,
            markdown=False,  # Disable markdown for cleaner output
            debug_mode=False
        )
        
        self._intelligence_agents[username] = agent
        return agent
    
    async def _get_next_steps_agent(self, username: str) -> Agent:
        """Get or create suggested next steps agent for user."""
        if username in self._next_steps_agents:
            return self._next_steps_agents[username]
        
        db_file = os.path.join(self._db_dir, f"next_steps_{username}.db")
        
        agent = Agent(
            name="Next Steps Advisor",
            model=OpenAIChat(id="gpt-4o"),
            instructions="""You are a financial planning advisor. Your role is to suggest concrete, actionable next steps based on financial conversations and profiles.

CRITICAL FORMATTING RULES:
- Keep steps brief and focused (3-5 steps maximum)
- Use minimal markdown: only use **bold** for emphasis on key actions, *italics* for subtle emphasis
- NO code blocks, headers, lists with markdown syntax, or complex formatting
- Write in plain text with simple bold/italics only
- Each step should be a clear, actionable statement

Generate 3-5 specific, actionable next steps that the client should consider. Each step should be:
- Clear and specific
- Actionable (something the client can do)
- Prioritized appropriately
- Relevant to their financial situation

Consider:
- Immediate actions needed
- Short-term goals (next 1-3 months)
- Medium-term planning (3-12 months)
- Risk management priorities
- Financial gaps to address

Provide steps as a prioritized list. Assign priority (High, Medium, Low) based on urgency and importance.
Note: These should be next steps FOR THE CLIENT to take, not questions the agent should ask.""",
            db=SqliteDb(db_file=db_file),
            user_id=f"{username}_next_steps",
            output_schema=SuggestedNextStepsResult,
            markdown=False,  # Disable markdown for cleaner output
            debug_mode=False
        )
        
        self._next_steps_agents[username] = agent
        return agent
    
    async def generate_intelligence_summary(
        self,
        username: str,
        conversation_context: str,
        profile_data: Optional[Dict[str, Any]] = None
    ) -> IntelligenceSummaryResult:
        """
        Generate intelligence summary from conversation and profile.
        
        Args:
            username: Username
            conversation_context: Recent conversation text
            profile_data: Current financial profile data
        
        Returns:
            IntelligenceSummaryResult with summary and insights
        """
        try:
            agent = await self._get_intelligence_agent(username)
            
            # Build prompt with context
            prompt = f"""Analyze the following financial conversation and profile data to generate intelligence insights.

Conversation Context:
{conversation_context}

Profile Data:
{self._format_profile_for_analysis(profile_data) if profile_data else "No profile data available yet."}

Generate a concise summary (2-3 sentences) and 2-4 key insights.
Keep it brief and focused. Use minimal formatting - only bold/italics for emphasis if needed."""
            
            # Run agent (async if available, otherwise sync)
            try:
                response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            except AttributeError:
                response = agent.run(prompt)
            
            # Extract structured output
            if hasattr(response, 'content') and isinstance(response.content, IntelligenceSummaryResult):
                return response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                return IntelligenceSummaryResult(**response.content)
            else:
                # Fallback: parse text response
                content = response.content if hasattr(response, 'content') else str(response)
                return IntelligenceSummaryResult(
                    summary=content[:200] if len(content) > 200 else content,
                    insights=[content[i:i+100] for i in range(0, min(len(content), 400), 100)]
                )
        
        except Exception as e:
            # Return default on error
            print(f"Error generating intelligence summary: {e}")
            return IntelligenceSummaryResult(
                summary="Analysis in progress...",
                insights=["Reviewing financial data", "Analyzing conversation patterns"]
            )
    
    async def generate_suggested_next_steps(
        self,
        username: str,
        conversation_context: str,
        profile_data: Optional[Dict[str, Any]] = None
    ) -> SuggestedNextStepsResult:
        """
        Generate suggested next steps from conversation and profile.
        
        Args:
            username: Username
            conversation_context: Recent conversation text
            profile_data: Current financial profile data
        
        Returns:
            SuggestedNextStepsResult with steps and priority
        """
        try:
            agent = await self._get_next_steps_agent(username)
            
            # Build prompt with context
            prompt = f"""Based on the following financial conversation and profile, suggest actionable next steps FOR THE CLIENT to take.

Conversation Context:
{conversation_context}

Profile Data:
{self._format_profile_for_analysis(profile_data) if profile_data else "No profile data available yet."}

Generate 3-5 specific, actionable next steps that the client should take (not questions for the agent to ask).
Each step should be clear, actionable, and prioritized. Use minimal formatting - only bold/italics for emphasis if needed."""
            
            # Run agent (async if available, otherwise sync)
            try:
                response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            except AttributeError:
                response = agent.run(prompt)
            
            # Extract structured output
            if hasattr(response, 'content') and isinstance(response.content, SuggestedNextStepsResult):
                return response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                return SuggestedNextStepsResult(**response.content)
            else:
                # Fallback: parse text response
                content = response.content if hasattr(response, 'content') else str(response)
                steps = [line.strip() for line in content.split('\n') if line.strip() and not line.strip().startswith('#')]
                return SuggestedNextStepsResult(
                    steps=steps[:5] if len(steps) > 5 else steps,
                    priority="Medium"
                )
        
        except Exception as e:
            # Return default on error
            print(f"Error generating suggested next steps: {e}")
            return SuggestedNextStepsResult(
                steps=["Continue the conversation to gather more information"],
                priority="Medium"
            )
    
    def _format_profile_for_analysis(self, profile_data: Dict[str, Any]) -> str:
        """Format profile data for agent analysis."""
        parts = []
        
        if profile_data.get("goals"):
            parts.append(f"Goals: {len(profile_data['goals'])} goal(s)")
        
        if profile_data.get("assets"):
            total_assets = sum(asset.get("value", 0) for asset in profile_data["assets"] if asset.get("value"))
            parts.append(f"Total Assets: ${total_assets:,.2f}")
        
        if profile_data.get("liabilities"):
            total_liabilities = sum(liab.get("amount", 0) for liab in profile_data["liabilities"] if liab.get("amount"))
            parts.append(f"Total Liabilities: ${total_liabilities:,.2f}")
        
        if profile_data.get("income"):
            parts.append(f"Income: ${profile_data['income']:,.2f} annually")
        
        if profile_data.get("risk_tolerance"):
            parts.append(f"Risk Tolerance: {profile_data['risk_tolerance']}")
        
        if profile_data.get("financial_stage"):
            parts.append(f"Financial Stage: {profile_data['financial_stage']}")
        
        return "\n".join(parts) if parts else "Profile data available but no specific details extracted yet."

