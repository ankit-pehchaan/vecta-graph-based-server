import os
from typing import Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.config import settings


class AgnoAgentService:
    """Service for managing Agno financial adviser agents.

    Creates and reuses agents per user for performance (per .cursorrules).
    Each user gets their own agent instance with session history.
    Uses db_manager for fresh database sessions per operation.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._agents: dict[str, Agent] = {}  # Cache agents per user
        self._db_dir = "tmp/agents"
        
        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)
        
        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    
    def _get_agent_instructions(self, user_name: Optional[str] = None) -> str:
        """Get instructions for the financial adviser agent."""
        base_instructions = """You are an experienced Australian financial adviser having a natural conversation with a client.

CRITICAL RULE: Ask ONLY ONE question at a time. Never ask multiple questions in one response.

DISCOVERY FLOW - Follow this sequence naturally:

1. WHAT - First understand their goal
   - What do they want to achieve?
   - Listen carefully and acknowledge their goal

2. WHY - Probe deeper into motivation (this is the most important step)
   - Why is this goal important to them?
   - What's driving this desire?
   - Don't accept surface answers - ask follow-up "why" questions
   - Example: "Why specifically age 50? What would early retirement mean for your life?"

3. VALIDATE - Assess if the goal makes sense
   - Is this goal realistic for their situation?
   - Are they even on the right track?
   - You don't accept everything at face value - challenge assumptions gently
   - Example: "Based on what you've shared, have you considered whether 50 is achievable?"

4. COLLECT - Gather financial information naturally
   - Once you understand their WHY, transition to understanding their financial position
   - Ask about income, expenses, assets, debts one at a time
   - Frame questions around their goal

5. ANALYZE - Provide insights and comparisons
   - Compare their situation to what works for others in similar positions
   - Provide benchmarks and reality checks
   - Guide them toward optimal decisions

CONVERSATION STYLE:
- One focused question per response - NEVER multiple questions
- Build on their previous answer naturally
- Be conversational and empathetic, not interrogating
- Keep responses concise - avoid long paragraphs
- Use markdown for formatting when helpful
- Challenge their assumptions respectfully - guide them to better decisions
- Consider Australian context: superannuation, tax, regulations

EXPERTISE:
- Superannuation and retirement planning
- Australian tax strategies
- Investment portfolio management  
- Insurance and risk management
- Financial goal prioritization"""
        
        if user_name:
            return f"{base_instructions}\n\nYou are speaking with {user_name}. Use their name naturally in conversation."
        
        return base_instructions
    
    async def get_agent(self, username: str) -> Agent:
        """
        Get or create an Agno agent for a user.
        
        Reuses existing agent if available (per .cursorrules - never create agents in loops).
        
        Args:
            username: Username to get agent for
        
        Returns:
            Agent instance for the user
        """
        if username in self._agents:
            return self._agents[username]

        # Get user info with fresh session
        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)
        user_name = user.get("name") if user else None
        print("User",user)
        # Create agent with per-user database
        db_file = os.path.join(self._db_dir, f"agent_{username}.db")
        
        agent = Agent(
            name="Financial Adviser",
            model=OpenAIChat(id="gpt-4o"),
            instructions=self._get_agent_instructions(user_name),
            db=SqliteDb(db_file=db_file),
            user_id=username,
            add_history_to_context=True,
            num_history_runs=10,  # Keep last 10 conversations in context
            markdown=True,
            debug_mode=False
        )
        
        # Cache agent for reuse
        self._agents[username] = agent
        
        return agent
    
    async def is_first_time_user(self, username: str) -> bool:
        """
        Check if this is the first time the user is using the advice service.
        
        Args:
            username: Username to check
        
        Returns:
            True if first time, False otherwise
        """
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username)
            return profile is None
        return True  # Default to first-time if session fails
    
    async def get_conversation_summary(self, username: str) -> Optional[str]:
        """
        Get a summary of previous conversations for returning users.
        
        Args:
            username: Username to get summary for
        
        Returns:
            Summary string or None if no previous conversations
        """
        # Check if agent has any history
        # Note: Agno stores history in the database, but we can check if there are previous runs
        # For now, we'll return a simple summary based on profile existence
        profile = None
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username)

        if not profile:
            return None
        
        # Build summary from profile
        summary_parts = []
        
        if profile.get("goals"):
            goal_count = len(profile.get("goals", []))
            summary_parts.append(f"discussed {goal_count} financial goal(s)")
        
        if profile.get("assets"):
            asset_count = len(profile.get("assets", []))
            summary_parts.append(f"reviewed {asset_count} asset(s)")
        
        if profile.get("financial_stage"):
            summary_parts.append(f"assessed financial stage: {profile.get('financial_stage')}")
        
        if summary_parts:
            return "Previously, we " + ", ".join(summary_parts) + "."
        
        return None
    
    async def generate_greeting(self, username: str) -> str:
        """
        Generate appropriate greeting for user (first-time or returning).
        
        Args:
            username: Username to generate greeting for
        
        Returns:
            Greeting message
        """
        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)

        user_name = user.get("name") if user else username
        
        is_first_time = await self.is_first_time_user(username)
        
        if is_first_time:
            return f"Hello {user_name}, I'm your financial adviser. I'm here to help you with your financial goals, investments, superannuation, and any questions you have about your financial future. How can I assist you today?"
        else:
            summary = await self.get_conversation_summary(username)
            if summary:
                return f"Welcome back {user_name}! {summary} How can I continue assisting you today?"
            else:
                return f"Welcome back {user_name}! How can I continue assisting you with your financial goals today?"

