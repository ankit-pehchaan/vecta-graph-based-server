import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.schemas.financial import FinancialProfile, Goal, Asset, Liability, Insurance
from app.interfaces.financial_profile import IFinancialProfileRepository
from app.core.config import settings


class ExtractedGoal(BaseModel):
    """A financial goal extracted from conversation."""
    description: str = Field(..., description="Description of the goal, e.g. 'Retire at 50', 'Buy a house', 'Save for kids education'")
    amount: Optional[float] = Field(default=None, description="Target amount in AUD if mentioned")
    timeline_years: Optional[float] = Field(default=None, description="Timeline in years if mentioned")
    priority: Optional[str] = Field(default=None, description="Priority: High, Medium, or Low")

class ExtractedAsset(BaseModel):
    """An asset extracted from conversation."""
    asset_type: str = Field(..., description="Type: australian_shares, managed_funds, family_home, investment_property, savings, term_deposits, bonds, cryptocurrency, other")
    description: str = Field(..., description="Description of the asset")
    value: Optional[float] = Field(default=None, description="Value in AUD if mentioned")
    institution: Optional[str] = Field(default=None, description="Institution name if mentioned")

class ExtractedLiability(BaseModel):
    """A liability extracted from conversation."""
    liability_type: str = Field(..., description="Type: home_loan, car_loan, personal_loan, credit_card, investment_loan, other")
    description: str = Field(..., description="Description of the liability")
    amount: Optional[float] = Field(default=None, description="Outstanding balance in AUD if mentioned")
    monthly_payment: Optional[float] = Field(default=None, description="Monthly payment if mentioned")
    interest_rate: Optional[float] = Field(default=None, description="Interest rate if mentioned")

class ExtractedInsurance(BaseModel):
    """Insurance policy extracted from conversation."""
    insurance_type: str = Field(..., description="Type: life, health, income_protection, TPD, trauma, home_insurance, car_insurance, other")
    provider: Optional[str] = Field(default=None, description="Insurance provider if mentioned")
    coverage_amount: Optional[float] = Field(default=None, description="Coverage amount in AUD if mentioned")

class ProfileExtractionResult(BaseModel):
    """Structured output from profile extraction agent."""
    goals: Optional[List[ExtractedGoal]] = Field(default_factory=list, description="Financial goals mentioned by the user")
    assets: Optional[List[ExtractedAsset]] = Field(default_factory=list, description="Assets owned by the user")
    liabilities: Optional[List[ExtractedLiability]] = Field(default_factory=list, description="Debts/loans owed by the user")
    insurance: Optional[List[ExtractedInsurance]] = Field(default_factory=list, description="Insurance policies held by the user")
    cash_balance: Optional[float] = Field(default=None, description="Cash balance mentioned (in AUD)")
    superannuation: Optional[float] = Field(default=None, description="Superannuation balance mentioned (in AUD)")
    income: Optional[float] = Field(default=None, description="Annual income mentioned (in AUD)")
    monthly_income: Optional[float] = Field(default=None, description="Monthly income mentioned (in AUD)")
    expenses: Optional[float] = Field(default=None, description="Monthly expenses mentioned (in AUD)")
    risk_tolerance: Optional[str] = Field(default=None, description="Risk tolerance: Low, Medium, or High")


class ProfileExtractor:
    """Service for extracting financial profile information using LLM agent.
    
    Uses Agno agent with structured output to accurately extract financial facts
    from conversations. No regex or hardcoded rules - pure LLM extraction.
    """
    
    def __init__(self, profile_repository: IFinancialProfileRepository):
        self.profile_repository = profile_repository
        self._agents: dict[str, Agent] = {}  # Cache agents per user
        self._db_dir = "tmp/agents"
        
        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)
        
        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    
    def _get_extraction_agent(self, username: str) -> Agent:
        """Get or create profile extraction agent for user."""
        if username in self._agents:
            return self._agents[username]
        
        db_file = os.path.join(self._db_dir, f"profile_extractor_{username}.db")
        
        agent = Agent(
            name="Financial Profile Extractor",
            model=OpenAIChat(id="gpt-4o"),
            instructions="""You are a financial data extraction specialist. Extract financial information from user messages.

EXAMPLES:
- "I want to retire at 50" → Goal with description: "Retire at 50"
- "I have $100k in savings" → cash_balance: 100000
- "I own a house worth $800k" → Asset with asset_type: "family_home", description: "Family home", value: 800000
- "I have a $500k mortgage" → Liability with liability_type: "home_loan", description: "Home loan", amount: 500000
- "I have life insurance" → Insurance with insurance_type: "life"

RULES:
1. Extract what is mentioned - don't infer
2. Use Australian Dollars (AUD)
3. For goals: ALWAYS include a clear description of what the user wants
4. For assets/liabilities: include type and description
5. Only extract NEW information not already in the existing profile

Be thorough - if the user mentions ANY financial goal, asset, debt, or number, extract it.""",
            db=SqliteDb(db_file=db_file),
            user_id=f"{username}_extractor",
            output_schema=ProfileExtractionResult,
            markdown=False,
            debug_mode=False
        )
        
        self._agents[username] = agent
        return agent
    
    async def extract_and_update_profile(
        self,
        username: str,
        conversation_text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract financial facts from conversation text using LLM agent and update profile.
        
        Args:
            username: Username to update profile for
            conversation_text: Text from agent response or user message
        
        Returns:
            Dictionary of changes made, or None if no changes
        """
        # Get existing profile or create new one
        existing_profile = await self.profile_repository.get_by_username(username)
        
        if not existing_profile:
            # Create new profile
            profile_data = {
                "username": username,
                "goals": [],
                "assets": [],
                "liabilities": [],
                "insurance": [],
                "cash_balance": None,
                "superannuation": None
            }
            existing_profile = await self.profile_repository.save(profile_data)
        
        # Build prompt with existing profile context
        existing_profile_summary = self._format_existing_profile(existing_profile)
        
        prompt = f"""Extract financial information from the following conversation text.

EXISTING PROFILE (do not re-extract these):
{existing_profile_summary}

CONVERSATION TEXT TO ANALYZE:
{conversation_text}

Extract ONLY NEW financial information that is not already in the existing profile. Return empty lists/None for fields where no new information is found."""
        
        try:
            # Get agent and extract
            agent = self._get_extraction_agent(username)
            
            # Run agent (async if available, otherwise sync)
            try:
                response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            except AttributeError:
                response = agent.run(prompt)
            
            print(f"[ProfileExtractor] Raw response type: {type(response.content) if hasattr(response, 'content') else type(response)}")
            
            # Extract structured output
            if hasattr(response, 'content') and isinstance(response.content, ProfileExtractionResult):
                extraction_result = response.content
                print(f"[ProfileExtractor] Got ProfileExtractionResult directly")
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                extraction_result = ProfileExtractionResult(**response.content)
                print(f"[ProfileExtractor] Parsed dict to ProfileExtractionResult")
            else:
                # Fallback: try to parse as dict
                content = response.content if hasattr(response, 'content') else str(response)
                print(f"[ProfileExtractor] Fallback - content type: {type(content)}")
                if isinstance(content, dict):
                    extraction_result = ProfileExtractionResult(**content)
                else:
                    # No extraction possible
                    print(f"[ProfileExtractor] No extraction possible, returning None")
                    return None
            
            print(f"[ProfileExtractor] Extraction result: goals={len(extraction_result.goals or [])}, assets={len(extraction_result.assets or [])}, liabilities={len(extraction_result.liabilities or [])}, cash_balance={extraction_result.cash_balance}, superannuation={extraction_result.superannuation}")
            
        except Exception as e:
            print(f"Error in profile extraction: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # Merge extracted data with existing profile - simple: just add whatever was extracted
        changes = {}
        updated = False
        now = datetime.now(timezone.utc).isoformat()
        
        # Helper to convert Pydantic model or dict to dict
        def to_dict(item):
            if hasattr(item, 'model_dump'):
                return item.model_dump()
            return item
        
        # Process goals - add all extracted goals
        if extraction_result.goals and len(extraction_result.goals) > 0:
            goals_list = []
            for g in extraction_result.goals:
                goal_dict = to_dict(g)
                goal_dict["created_at"] = now
                goals_list.append(goal_dict)
                print(f"[ProfileExtractor] Goal extracted: {goal_dict.get('description', 'No description')}")
            existing_profile["goals"].extend(goals_list)
            changes["goals"] = goals_list
            updated = True
            print(f"[ProfileExtractor] Added {len(goals_list)} goal(s)")
        
        # Process assets - add all extracted assets
        if extraction_result.assets and len(extraction_result.assets) > 0:
            assets_list = []
            for a in extraction_result.assets:
                asset_dict = to_dict(a)
                asset_dict["created_at"] = now
                assets_list.append(asset_dict)
            existing_profile["assets"].extend(assets_list)
            changes["assets"] = assets_list
            updated = True
            print(f"[ProfileExtractor] Added {len(assets_list)} asset(s)")
        
        # Process liabilities - add all extracted liabilities
        if extraction_result.liabilities and len(extraction_result.liabilities) > 0:
            liabilities_list = []
            for l in extraction_result.liabilities:
                liability_dict = to_dict(l)
                liability_dict["created_at"] = now
                liabilities_list.append(liability_dict)
            existing_profile["liabilities"].extend(liabilities_list)
            changes["liabilities"] = liabilities_list
            updated = True
            print(f"[ProfileExtractor] Added {len(liabilities_list)} liability(ies)")
        
        # Process insurance - add all extracted insurance
        if extraction_result.insurance and len(extraction_result.insurance) > 0:
            insurance_list = []
            for i in extraction_result.insurance:
                insurance_dict = to_dict(i)
                insurance_dict["created_at"] = now
                insurance_list.append(insurance_dict)
            existing_profile["insurance"].extend(insurance_list)
            changes["insurance"] = insurance_list
            updated = True
            print(f"[ProfileExtractor] Added {len(insurance_list)} insurance policy(ies)")
        
        # Process cash balance
        if extraction_result.cash_balance is not None:
            if existing_profile.get("cash_balance") != extraction_result.cash_balance:
                existing_profile["cash_balance"] = extraction_result.cash_balance
                changes["cash_balance"] = extraction_result.cash_balance
                updated = True
        
        # Process superannuation
        if extraction_result.superannuation is not None:
            if existing_profile.get("superannuation") != extraction_result.superannuation:
                existing_profile["superannuation"] = extraction_result.superannuation
                changes["superannuation"] = extraction_result.superannuation
                updated = True
        
        # Process income
        if extraction_result.income is not None:
            if existing_profile.get("income") != extraction_result.income:
                existing_profile["income"] = extraction_result.income
                changes["income"] = extraction_result.income
                updated = True
        
        if extraction_result.monthly_income is not None:
            if existing_profile.get("monthly_income") != extraction_result.monthly_income:
                existing_profile["monthly_income"] = extraction_result.monthly_income
                changes["monthly_income"] = extraction_result.monthly_income
                updated = True
        
        # Process expenses
        if extraction_result.expenses is not None:
            if existing_profile.get("expenses") != extraction_result.expenses:
                existing_profile["expenses"] = extraction_result.expenses
                changes["expenses"] = extraction_result.expenses
                updated = True
        
        # Process risk tolerance
        if extraction_result.risk_tolerance is not None:
            if existing_profile.get("risk_tolerance") != extraction_result.risk_tolerance:
                existing_profile["risk_tolerance"] = extraction_result.risk_tolerance
                changes["risk_tolerance"] = extraction_result.risk_tolerance
                updated = True
        
        if updated:
            # Update profile in repository
            updated_profile = await self.profile_repository.update(username, existing_profile)
            print(f"[ProfileExtractor] Profile updated for {username}, changes: {list(changes.keys())}")
            return {
                "changes": changes,
                "profile": updated_profile
            }
        
        print(f"[ProfileExtractor] No changes detected for {username}")
        return None
    
    def _format_existing_profile(self, profile: Dict[str, Any]) -> str:
        """Format existing profile for agent context."""
        parts = []
        
        if profile.get("goals"):
            parts.append(f"Goals: {len(profile['goals'])} goal(s) already extracted")
        
        if profile.get("assets"):
            parts.append(f"Assets: {len(profile['assets'])} asset(s) already extracted")
        
        if profile.get("liabilities"):
            parts.append(f"Liabilities: {len(profile['liabilities'])} liability/ies already extracted")
        
        if profile.get("insurance"):
            parts.append(f"Insurance: {len(profile['insurance'])} policy/ies already extracted")
        
        if profile.get("cash_balance") is not None:
            parts.append(f"Cash balance: ${profile['cash_balance']:,.2f}")
        
        if profile.get("superannuation") is not None:
            parts.append(f"Superannuation: ${profile['superannuation']:,.2f}")
        
        if profile.get("income") is not None:
            parts.append(f"Income: ${profile['income']:,.2f} annually")
        
        if profile.get("expenses") is not None:
            parts.append(f"Expenses: ${profile['expenses']:,.2f} monthly")
        
        if profile.get("risk_tolerance"):
            parts.append(f"Risk tolerance: {profile['risk_tolerance']}")
        
        return "\n".join(parts) if parts else "No existing profile data."
