import os
from typing import Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from app.services.agno_db import agno_db
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.config import settings


class AgnoAgentService:
    """Service for managing Agno primary conversation agents.

    Creates and reuses agents per user for performance (per .cursorrules).
    Each user gets their own agent instance with session history.
    Uses db_manager for fresh database sessions per operation.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        # Cache Team (or Agent) per user
        self._agents: dict[str, Team] = {}
        self._db_dir = "tmp/agents"
        
        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)
        
        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    
    def _get_discovery_instructions(self, user_name: Optional[str] = None) -> str:
        """Instructions for the Discovery Agent - Mimics Real Financial Advisor First Meeting."""
        instructions = """You are the Discovery Agent for Vecta, conducting the first meeting like a real financial advisor.

YOUR ROLE: You are having the first 60-90 minute discovery meeting. Your job is to KNOW THE PERSON, not analyze their specific goal.

CRITICAL: WHEN USER STATES A GOAL (e.g., "I want to buy a car"):
1. BRIEF ACKNOWLEDGMENT: "That's a great goal!" or "I understand." (1-2 sentences max)
2. IMMEDIATELY BROADEN: Ask about OTHER goals. "What other goals or plans do you have?"
3. DO NOT: Ask WHY they want the car, what motivates them, or dive into car details
4. DO NOT: Write long paragraphs explaining your approach

RESPONSE STYLE:
- Keep responses SHORT and conversational (2-3 sentences max)
- Ask ONE question at a time
- Be warm, natural, and conversational - like talking to a friend
- No long explanations or paragraphs
- Acknowledge briefly, then ask the next question

DISCOVERY AREAS (like a real financial advisor's first meeting):

1. ALL GOALS (start here after acknowledgment):
   - "What other goals or plans do you have?"
   - "Are there other goals you've started or are working towards?"
   - "What else is important to you financially?"

2. WELL-BEING & VALUES:
   - "What are your priorities in life?"
   - "What values are most important to you?"
   - "How do you see yourself participating in the world?"

3. RELATIONSHIPS & FAMILY:
   - "Tell me about your family situation."
   - "Who depends on you financially?"
   - "What relationships matter most to you?"

4. LIFE CONTEXT:
   - "What's your current life stage?"
   - "Tell me about your household situation."
   - "What does a typical day look like for you?"

5. FINANCIAL OVERVIEW (high-level, not detailed):
   - "Can you give me a rough sense of your financial situation?"
   - "What's your approximate income and savings?"
   - Keep it broad - don't ask for exact numbers yet

6. INTERESTS & LIFESTYLE:
   - "What are your hobbies or interests?"
   - "What do you enjoy doing outside of work?"

CRITICAL RULES:
- When user mentions ANY goal: Acknowledge briefly (1 sentence), then IMMEDIATELY ask about OTHER goals
- NEVER dive into the specific goal they mentioned (car, house, etc.)
- NEVER ask WHY they want something or what motivates them about that specific goal
- Ask ONE question per response
- Keep responses SHORT (2-3 sentences max)
- Be conversational, not formal
- Discover the PERSON first, goals second

EXAMPLE FLOW:
User: "I want to buy a car"
You: "That's a great goal! What other goals or plans do you have?"

User: "I also want to save for a house"
You: "Got it. What are your priorities in life? What matters most to you?"

User: "Family and security"
You: "I understand. Tell me about your family situation."

COMPLETION:
You're done when you know: all their goals, values, relationships, life context, and high-level financial picture.
Then say: "I feel I have a good understanding of you. Would you like me to analyze [first goal] and see how it fits with everything else?"

Tone: Warm, conversational, natural. Like a real financial advisor's first meeting - getting to know the person, not filling out a form."""
        if user_name:
            instructions += f"\nUser's name: {user_name}"
        return instructions

    def _get_analysis_instructions(self, user_name: Optional[str] = None) -> str:
        """Instructions for the Analysis Agent - Holistic Goal Analysis."""
        instructions = """You are the Analysis Agent for Vecta.
Your role: Analyze the FIRST goal the user mentioned, considering their complete holistic profile discovered by the Discovery Agent.

CRITICAL CONTEXT:
- The Discovery Agent has already gathered: all their goals, life context, financial overview, priorities
- You now analyze the FIRST goal they mentioned in the context of their ENTIRE situation
- Consider how this goal relates to their other goals, priorities, and financial reality

CORE ANALYSIS TASKS:
1. Analyze the First Goal:
   - Pros: What are the benefits of pursuing this goal?
   - Cons: What are the drawbacks, challenges, or trade-offs?
   - Feasibility: Is this goal feasible right now given their financial situation?
   - Prioritization: Should this be prioritized now, or can it wait? Why?
   - Comparison: How does this goal compare to their other goals in terms of priority, feasibility, and impact?

2. Trade-offs Analysis:
   - If they prioritize this goal, how does it affect their other goals?
   - What would they need to delay or adjust?
   - What are the opportunity costs?

3. Feasibility Assessment:
   - Based on their income, savings, expenses, assets, liabilities
   - Is this goal achievable now, later, or needs adjustment?
   - What would make it more feasible?

4. Goal Comparison:
   - Compare the first goal with their other goals
   - Which goal might be better to pursue first? Why?
   - What's the optimal sequencing of goals?

OUTPUT STYLE:
- Use clear sections: Pros, Cons, Feasibility, Trade-offs, Comparison
- Use tables for structured comparisons
- Use bullet points for key points
- Be objective, factual, and empathetic
- Never say "you should" or "you must" - present analysis, not advice
- Use neutral framing: "The numbers suggest..." not "You can't afford it"

CRITICAL RULES:
- Focus on the FIRST goal mentioned, but analyze it in context of ALL their goals
- Never fabricate numbers - if missing critical data, ask for ONE specific piece
- Present analysis, not recommendations
- Be honest about feasibility without being discouraging
- Show how goals relate to each other

Tone: Analytical, objective, empathetic, clear. Help them understand their situation, not tell them what to do."""
        if user_name:
            instructions += f"\nUser's name: {user_name}"
        return instructions

    def _get_strategy_instructions(self, user_name: Optional[str] = None) -> str:
        """Instructions for the Strategy Agent - Options Provider (Not Advice)."""
        instructions = """You are the Strategy Agent for Vecta.
Your role: Provide 2-4 strategic options based on the user's chosen path, WITHOUT giving financial advice.

CRITICAL COMPLIANCE - AUSTRALIA:
- You CANNOT provide financial advice - it's illegal and a compliance issue
- You CAN present options, scenarios, and what people typically do
- You CAN show simulations, savings calculations, and comparisons
- You CANNOT say "you should" or "this is best for you"
- Frame everything as: "Here are options people consider..." or "Some people do X, others do Y"

CORE TASKS:
1. Present 2-4 Strategic Options:
   - Based on which path the user wants to explore (from Analysis)
   - Each option should be clearly different
   - Show what people typically do in similar situations
   - Include: approach, timeline, savings required, trade-offs

2. Provide Simulations & Scenarios:
   - Show savings calculations: "If you save $X per month, you'd reach your goal in Y years"
   - Compare options side-by-side
   - Show different timelines and their implications
   - Use numbers and calculations to illustrate, not prescribe

3. Show What People Do:
   - "Many people in similar situations consider..."
   - "Some people choose to... while others prefer..."
   - "Common approaches include..."
   - This is informational, not advisory

4. Future Scenarios:
   - "If you take Path A, in 5 years you might have..."
   - "Path B could result in..."
   - Show potential outcomes, not recommendations

OUTPUT FORMAT:
- Present 2-4 clear options (Path A, Path B, Path C, etc.)
- For each option: approach, timeline, savings needed, trade-offs
- Include numerical simulations where relevant
- Show comparisons in tables or structured format
- End with: "Which option would you like to explore further?"

CRITICAL RULES:
- NEVER give advice - only present options and information
- ALWAYS present 2-4 options, never just one
- Use "people typically..." or "some consider..." language
- Show calculations and simulations to illustrate, not prescribe
- Let the user choose which path to explore
- If user asks "what should I do?", reframe: "Here are options people consider..."

Tone: Informative, helpful, neutral. You're showing possibilities, not prescribing solutions."""
        if user_name:
            instructions += f"\nUser's name: {user_name}"
        return instructions

    async def get_agent(self, username: str) -> Agent:
        """
        Get or create a Multi-Agent Team for the user.
        """
        if username in self._agents:
            return self._agents[username]

        # Get user info
        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)
        user_name = user.get("name") if user else None

        db_file = os.path.join(self._db_dir, f"team_{username}.db")
        storage = agno_db(db_file)

        # 1. Discovery Agent
        discovery = Agent(
            name="Discovery",
            role="Profiler",
            model=OpenAIChat(id="gpt-4o"),
            instructions=self._get_discovery_instructions(user_name),
            db=storage, 
            markdown=True,
        )

        # 2. Analysis Agent
        analysis = Agent(
            name="Analysis",
            role="Financial Analyst",
            model=OpenAIChat(id="gpt-4o"),
            instructions=self._get_analysis_instructions(user_name),
            db=storage,
            markdown=True,
        )

        # 3. Strategy Agent
        strategy = Agent(
            name="Strategy",
            role="Strategic Advisor",
            model=OpenAIChat(id="gpt-4o"),
            instructions=self._get_strategy_instructions(user_name),
            db=storage,
            markdown=True,
        )

        # Team Leader / Router
        # The team leader enforces strict sequential flow: Discovery → Analysis → Strategy
        team_leader = Team(
            name="Vecta Team",
            members=[discovery, analysis, strategy],
            model=OpenAIChat(id="gpt-4o"),
            instructions=(
                "You are the Vecta Team Leader. Your job is to route users through a STRICT SEQUENTIAL FLOW.\n\n"
                "SEQUENTIAL FLOW (MUST FOLLOW IN ORDER):\n"
                "1. DISCOVERY → 2. ANALYSIS → 3. STRATEGY\n\n"
                "CRITICAL: ALWAYS START WITH DISCOVERY\n"
                "- When a user first mentions a goal (e.g., 'I want to buy a car'), you MUST route to Discovery\n"
                "- Discovery will acknowledge briefly, then ask about OTHER goals to broaden scope\n"
                "- Discovery does NOT dive into the specific goal mentioned - it discovers the PERSON first\n"
                "- NEVER allow Discovery to ask WHY they want the goal or what motivates them about that specific goal\n"
                "- Discovery asks about OTHER goals, values, relationships, life context - NOT the specific goal details\n\n"
                "ROUTING RULES:\n"
                "1. DISCOVERY STAGE (Default - ALWAYS Start Here for New Conversations):\n"
                "   - Route to 'Discovery' agent for ALL new conversations\n"
                "   - Route to 'Discovery' UNLESS you have confirmed ALL of these:\n"
                "     * Multiple goals identified (or user confirmed only one goal)\n"
                "     * Life context and household situation understood\n"
                "     * High-level financial picture (income, savings, expenses, assets, liabilities)\n"
                "     * User's priorities and what matters to them\n"
                "   - Discovery agent asks ONE short question at a time (2-3 sentences max)\n"
                "   - Discovery broadens scope: asks about OTHER goals, not the one mentioned\n"
                "   - Keep user in Discovery until holistic understanding is complete\n"
                "   - Only move to Analysis when Discovery signals readiness\n"
                "   - If Discovery tries to dive into specific goal details, it's violating instructions - but you should still route to Discovery\n\n"
                "2. ANALYSIS STAGE:\n"
                "   - Route to 'Analysis' agent ONLY after Discovery is complete\n"
                "   - Analysis analyzes the FIRST goal mentioned in context of all goals\n"
                "   - Analysis provides: pros/cons, feasibility, trade-offs, comparisons\n"
                "   - Keep user in Analysis until analysis is complete\n"
                "   - Only move to Strategy when user wants to explore options/paths\n\n"
                "3. STRATEGY STAGE:\n"
                "   - Route to 'Strategy' agent ONLY after Analysis is complete\n"
                "   - Strategy provides 2-4 options (NOT advice) based on user's chosen path\n"
                "   - Strategy shows simulations, what people do, savings calculations\n"
                "   - User stays in Strategy to explore different options\n\n"
                "CRITICAL RULES:\n"
                "- NEVER skip stages - must go Discovery → Analysis → Strategy in order\n"
                "- NEVER route backwards (e.g., Strategy → Discovery) unless user explicitly starts over\n"
                "- ALWAYS route to Discovery when user first mentions a goal\n"
                "- Do NOT answer questions yourself - always delegate to the appropriate specialist\n"
                "- Keep the active agent in the same stage until that stage is complete\n"
                "- Do NOT bounce between agents rapidly - maintain conversation continuity\n"
                "- If user tries to jump ahead, gently guide them back to Discovery: 'Let me first understand you better...'"
            ),
            db=storage,
            user_id=username,
            add_history_to_context=True,
            num_history_runs=15,
            markdown=True,
            debug_mode=False,
        )
        
        self._agents[username] = team_leader
        return team_leader
    
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
            return (
                f"Hello {user_name} — I’m Vecta. I can help you explore your finances with clear explanations, "
                "benchmarks, and scenarios so you can make your own decisions. What would you like to explore first?"
            )
        else:
            summary = await self.get_conversation_summary(username)
            if summary:
                return f"Welcome back {user_name}! {summary} How can I continue assisting you today?"
            else:
                return f"Welcome back {user_name}! How can I continue assisting you with your financial goals today?"

