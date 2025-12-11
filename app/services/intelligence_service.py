import os
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.core.config import settings


class IntelligenceService:
    """Service for generating streaming intelligence summaries using Agno agents.
    
    Creates and reuses agents per user for performance (per .cursorrules).
    """
    
    def __init__(self):
        self._intelligence_agents: dict[str, Agent] = {}  # Cache agents per user
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
            model=OpenAIChat(id="gpt-4.1"),
            instructions="""You are a financial intelligence analyst. Generate brief, actionable insights.

RULES - STRICTLY FOLLOW:
- Summary: 2-3 sentences maximum
- Insights: 2-3 bullet points maximum
- PLAIN TEXT ONLY - no markdown, no bold, no formatting, no asterisks
- Be specific and professional
- Focus on actionable intelligence only

Analyze the conversation and profile to identify:
- Key financial patterns
- Risks or opportunities
- Gaps needing attention

Keep it short and concise. No rich text formatting.""",
            db=SqliteDb(db_file=db_file),
            user_id=f"{username}_intelligence",
            markdown=False,
            debug_mode=False
        )
        
        self._intelligence_agents[username] = agent
        return agent
    
    async def stream_intelligence_summary(
        self,
        username: str,
        conversation_context: str,
        profile_data: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream intelligence summary from conversation and profile.
        
        Args:
            username: Username (email)
            conversation_context: Recent conversation text
            profile_data: Current financial profile data
        
        Yields:
            Text chunks as they're generated
        """
        try:
            agent = await self._get_intelligence_agent(username)
            
            # Build prompt with context
            prompt = f"""Analyze and provide brief intelligence.

Conversation:
{conversation_context}

Profile:
{self._format_profile_for_analysis(profile_data) if profile_data else "No data yet."}

Give a 2-3 sentence summary, then 2-3 key insights. Plain text only, no formatting."""
            
            # Run agent and get full response
            try:
                response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            except AttributeError:
                response = agent.run(prompt)
            
            full_response = response.content if hasattr(response, 'content') else str(response)
            
            # Stream response in chunks for smooth UX
            chunk_size = 5  # Small chunks for smooth streaming
            for i in range(0, len(full_response), chunk_size):
                chunk = full_response[i:i + chunk_size]
                if chunk:
                    yield chunk
                    await asyncio.sleep(0.01)  # Small delay for smooth streaming
        
        except Exception as e:
            print(f"Error streaming intelligence summary: {e}")
            yield "Analysis in progress..."
    
    def _format_profile_for_analysis(self, profile_data: Dict[str, Any]) -> str:
        """Format profile data for agent analysis."""
        parts = []
        
        if profile_data.get("goals"):
            parts.append(f"Goals: {len(profile_data['goals'])} goal(s)")
        
        # Calculate cash balance from assets
        if profile_data.get("assets"):
            cash_assets = [
                a for a in profile_data["assets"] 
                if a.get("asset_type") in ("cash", "savings")
            ]
            if cash_assets:
                total_cash = sum(a.get("value", 0) for a in cash_assets if a.get("value"))
                parts.append(f"Cash/Savings: ${total_cash:,.2f}")
            
            total_assets = sum(asset.get("value", 0) for asset in profile_data["assets"] if asset.get("value"))
            parts.append(f"Total Assets: ${total_assets:,.2f}")
        
        # Superannuation totals
        if profile_data.get("superannuation"):
            total_super = sum(s.get("balance", 0) for s in profile_data["superannuation"] if s.get("balance"))
            parts.append(f"Total Superannuation: ${total_super:,.2f}")
            parts.append(f"Super Funds: {len(profile_data['superannuation'])} fund(s)")
        
        if profile_data.get("liabilities"):
            total_liabilities = sum(liab.get("amount", 0) for liab in profile_data["liabilities"] if liab.get("amount"))
            parts.append(f"Total Liabilities: ${total_liabilities:,.2f}")
        
        if profile_data.get("income"):
            parts.append(f"Income: ${profile_data['income']:,.2f} annually")
        
        if profile_data.get("monthly_income"):
            parts.append(f"Monthly Income: ${profile_data['monthly_income']:,.2f}")
        
        if profile_data.get("expenses"):
            parts.append(f"Monthly Expenses: ${profile_data['expenses']:,.2f}")
        
        if profile_data.get("risk_tolerance"):
            parts.append(f"Risk Tolerance: {profile_data['risk_tolerance']}")
        
        if profile_data.get("insurance"):
            parts.append(f"Insurance Policies: {len(profile_data['insurance'])} policy/ies")
        
        if profile_data.get("financial_stage"):
            parts.append(f"Financial Stage: {profile_data['financial_stage']}")
        
        return "\n".join(parts) if parts else "Profile data available but no specific details extracted yet."
