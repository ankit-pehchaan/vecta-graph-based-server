import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.schemas.financial import FinancialProfile, Goal, Asset, Liability, Insurance, Superannuation
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.config import settings
from app.core.prompts import PROFILE_EXTRACTOR_SYSTEM_PROMPT

# Configure logger
logger = logging.getLogger("profile_extractor")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


class ExtractedGoal(BaseModel):
    """A financial goal extracted from conversation."""
    description: str = Field(..., description="Description of the goal, e.g. 'Retire at 50', 'Buy a house', 'Save for kids education'")
    amount: Optional[float] = Field(default=None, description="Target amount in AUD if mentioned")
    timeline_years: Optional[float] = Field(default=None, description="Timeline in years if mentioned")
    priority: Optional[str] = Field(default=None, description="Priority: High, Medium, or Low")


class ExtractedAsset(BaseModel):
    """An asset extracted from conversation."""
    asset_type: str = Field(..., description="Type: cash, savings, shares, managed_funds, property, investment_property, term_deposits, bonds, crypto, other")
    description: str = Field(..., description="Description of the asset")
    value: Optional[float] = Field(default=None, description="Value in AUD if mentioned")
    institution: Optional[str] = Field(default=None, description="Institution name if mentioned")


class ExtractedLiability(BaseModel):
    """A liability extracted from conversation."""
    liability_type: str = Field(..., description="Type: home_loan, car_loan, personal_loan, credit_card, investment_loan, hecs, other")
    description: str = Field(..., description="Description of the liability")
    amount: Optional[float] = Field(default=None, description="Outstanding balance in AUD if mentioned")
    monthly_payment: Optional[float] = Field(default=None, description="Monthly payment if mentioned")
    interest_rate: Optional[float] = Field(default=None, description="Interest rate if mentioned")


class ExtractedInsurance(BaseModel):
    """Insurance policy extracted from conversation."""
    insurance_type: str = Field(..., description="Type: life, health, income_protection, tpd, trauma, home, car, other")
    provider: Optional[str] = Field(default=None, description="Insurance provider if mentioned")
    coverage_amount: Optional[float] = Field(default=None, description="Coverage amount in AUD if mentioned")


class ExtractedSuperannuation(BaseModel):
    """Superannuation fund extracted from conversation."""
    fund_name: str = Field(default="Primary Super Fund", description="Name of the super fund if mentioned")
    balance: Optional[float] = Field(default=None, description="Super balance in AUD if mentioned")
    employer_contribution_rate: Optional[float] = Field(default=None, description="Employer contribution percentage if mentioned")
    personal_contribution_rate: Optional[float] = Field(default=None, description="Personal contribution percentage if mentioned")
    investment_option: Optional[str] = Field(default=None, description="Investment option: Balanced, Growth, Conservative, High Growth")
    insurance_death: Optional[float] = Field(default=None, description="Death cover amount within super")
    insurance_tpd: Optional[float] = Field(default=None, description="TPD cover amount within super")


class ProfileExtractionResult(BaseModel):
    """Structured output from profile extraction agent."""
    # Persona fields (Phase 1)
    age: Optional[int] = Field(default=None, description="User's age if mentioned")
    relationship_status: Optional[str] = Field(default=None, description="Relationship status: single, partnered, married, divorced, widowed")
    has_kids: Optional[bool] = Field(default=None, description="Whether user has children")
    number_of_kids: Optional[int] = Field(default=None, description="Number of children if mentioned")
    career: Optional[str] = Field(default=None, description="Job, profession, or career description")
    location: Optional[str] = Field(default=None, description="City, region, or location if mentioned")

    # Life aspirations (Phase 2)
    marriage_plans: Optional[str] = Field(default=None, description="Marriage plans or timeline if mentioned")
    family_plans: Optional[str] = Field(default=None, description="Plans for having kids or more kids")
    career_goals: Optional[str] = Field(default=None, description="Career trajectory or future plans")
    retirement_age: Optional[int] = Field(default=None, description="Target retirement age if mentioned")
    retirement_vision: Optional[str] = Field(default=None, description="What retirement looks like to them")
    lifestyle_goals: Optional[str] = Field(default=None, description="Lifestyle aspirations mentioned")

    # Financial data (Phase 3)
    goals: Optional[List[ExtractedGoal]] = Field(default_factory=list, description="Financial goals mentioned by the user")
    assets: Optional[List[ExtractedAsset]] = Field(default_factory=list, description="Assets including cash, savings, investments, property")
    liabilities: Optional[List[ExtractedLiability]] = Field(default_factory=list, description="Debts/loans owed by the user")
    insurance: Optional[List[ExtractedInsurance]] = Field(default_factory=list, description="Insurance policies held by the user")
    superannuation: Optional[List[ExtractedSuperannuation]] = Field(default_factory=list, description="Superannuation funds")
    income: Optional[float] = Field(default=None, description="Annual income mentioned (in AUD)")
    monthly_income: Optional[float] = Field(default=None, description="Monthly income mentioned (in AUD)")
    expenses: Optional[float] = Field(default=None, description="Monthly expenses mentioned (in AUD)")
    risk_tolerance: Optional[str] = Field(default=None, description="Risk tolerance: Low, Medium, or High")


class ProfileExtractor:
    """Service for extracting financial profile information using LLM agent.

    Uses Agno agent with structured output to accurately extract financial facts
    from conversations. No regex or hardcoded rules - pure LLM extraction.
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

        logger.info("[INIT] ProfileExtractor initialized")
    
    def _get_extraction_agent(self, username: str) -> Agent:
        """Get or create profile extraction agent for user."""
        if username in self._agents:
            logger.debug(f"[EXTRACTION] Returning cached agent for: {username}")
            return self._agents[username]

        logger.debug(f"[EXTRACTION] Creating new agent for: {username}")
        db_file = os.path.join(self._db_dir, f"profile_extractor_{username}.db")

        agent = Agent(
            name="Financial Profile Extractor",
            model=OpenAIChat(id="gpt-4o-mini"),  # Use fast model for extraction
            instructions=PROFILE_EXTRACTOR_SYSTEM_PROMPT,
            db=SqliteDb(db_file=db_file),
            user_id=f"{username}_extractor",
            output_schema=ProfileExtractionResult,
            markdown=False,
            debug_mode=False
        )

        self._agents[username] = agent
        logger.info(f"[EXTRACTION] Created and cached agent for: {username}")
        return agent
    
    async def extract_and_update_profile(
        self,
        username: str,
        conversation_text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract financial facts from conversation text using LLM agent and update profile.
        
        Uses add_items() to ADD new items incrementally without replacing existing ones.
        
        Args:
            username: Username (email) to update profile for
            conversation_text: Text from agent response or user message
        
        Returns:
            Dictionary of changes made, or None if no changes
        """
        # Get existing profile for context (don't re-extract same info)
        existing_profile = None
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            existing_profile = await profile_repo.get_by_username(username)
        
        if not existing_profile:
            # User must exist - try to save initial financial data
            try:
                profile_data = {
                    "username": username,
                    "goals": [],
                    "assets": [],
                    "liabilities": [],
                    "insurance": [],
                    "superannuation": []
                }
                async for session in self.db_manager.get_session():
                    profile_repo = FinancialProfileRepository(session)
                    existing_profile = await profile_repo.save(profile_data)
            except ValueError:
                # User doesn't exist - can't save profile
                logger.warning(f"[EXTRACTION] User {username} not found, cannot extract profile")
                return None
        
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
            
            logger.debug(f"[EXTRACTION] Raw response type: {type(response.content) if hasattr(response, 'content') else type(response)}")

            # Extract structured output
            if hasattr(response, 'content') and isinstance(response.content, ProfileExtractionResult):
                extraction_result = response.content
                logger.debug("[EXTRACTION] Got ProfileExtractionResult directly")
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                extraction_result = ProfileExtractionResult(**response.content)
                logger.debug("[EXTRACTION] Parsed dict to ProfileExtractionResult")
            else:
                # Fallback: try to parse as dict
                content = response.content if hasattr(response, 'content') else str(response)
                logger.debug(f"[EXTRACTION] Fallback - content type: {type(content)}")
                if isinstance(content, dict):
                    extraction_result = ProfileExtractionResult(**content)
                else:
                    # No extraction possible
                    logger.debug("[EXTRACTION] No extraction possible, returning None")
                    return None

            logger.info(f"[EXTRACTION] Result: goals={len(extraction_result.goals or [])}, assets={len(extraction_result.assets or [])}, liabilities={len(extraction_result.liabilities or [])}, super={len(extraction_result.superannuation or [])}")
            
        except Exception as e:
            logger.error(f"[EXTRACTION] Error in profile extraction: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # Build new_items dictionary for add_items() - ONLY new data
        new_items = {}
        changes = {}
        now = datetime.now(timezone.utc).isoformat()
        
        # Helper to convert Pydantic model or dict to dict
        def to_dict(item):
            if hasattr(item, 'model_dump'):
                return item.model_dump()
            return item
        
        # Process goals - collect new goals
        if extraction_result.goals and len(extraction_result.goals) > 0:
            goals_list = []
            for g in extraction_result.goals:
                goal_dict = to_dict(g)
                goal_dict["created_at"] = now
                goals_list.append(goal_dict)
                logger.debug(f"[EXTRACTION] Goal extracted: {goal_dict.get('description', 'No description')}")
            new_items["goals"] = goals_list
            changes["goals"] = goals_list
            logger.info(f"[EXTRACTION] Will add {len(goals_list)} goal(s)")
        
        # Process assets - collect new assets (includes cash/savings)
        if extraction_result.assets and len(extraction_result.assets) > 0:
            assets_list = []
            for a in extraction_result.assets:
                asset_dict = to_dict(a)
                asset_dict["created_at"] = now
                assets_list.append(asset_dict)
            new_items["assets"] = assets_list
            changes["assets"] = assets_list
            logger.info(f"[EXTRACTION] Will add {len(assets_list)} asset(s)")
        
        # Process liabilities - collect new liabilities
        if extraction_result.liabilities and len(extraction_result.liabilities) > 0:
            liabilities_list = []
            for l in extraction_result.liabilities:
                liability_dict = to_dict(l)
                liability_dict["created_at"] = now
                liabilities_list.append(liability_dict)
            new_items["liabilities"] = liabilities_list
            changes["liabilities"] = liabilities_list
            logger.info(f"[EXTRACTION] Will add {len(liabilities_list)} liability(ies)")
        
        # Process insurance - collect new insurance
        if extraction_result.insurance and len(extraction_result.insurance) > 0:
            insurance_list = []
            for i in extraction_result.insurance:
                insurance_dict = to_dict(i)
                insurance_dict["created_at"] = now
                insurance_list.append(insurance_dict)
            new_items["insurance"] = insurance_list
            changes["insurance"] = insurance_list
            logger.info(f"[EXTRACTION] Will add {len(insurance_list)} insurance policy(ies)")
        
        # Process superannuation - collect new super funds
        if extraction_result.superannuation and len(extraction_result.superannuation) > 0:
            super_list = []
            for s in extraction_result.superannuation:
                super_dict = to_dict(s)
                super_dict["created_at"] = now
                super_dict["updated_at"] = now
                super_list.append(super_dict)
            new_items["superannuation"] = super_list
            changes["superannuation"] = super_list
            logger.info(f"[EXTRACTION] Will add {len(super_list)} superannuation fund(s)")
        
        # Process scalar fields (these will update existing values)
        if extraction_result.income is not None:
            if existing_profile.get("income") != extraction_result.income:
                new_items["income"] = extraction_result.income
                changes["income"] = extraction_result.income
        
        if extraction_result.monthly_income is not None:
            if existing_profile.get("monthly_income") != extraction_result.monthly_income:
                new_items["monthly_income"] = extraction_result.monthly_income
                changes["monthly_income"] = extraction_result.monthly_income
        
        if extraction_result.expenses is not None:
            if existing_profile.get("expenses") != extraction_result.expenses:
                new_items["expenses"] = extraction_result.expenses
                changes["expenses"] = extraction_result.expenses
        
        if extraction_result.risk_tolerance is not None:
            if existing_profile.get("risk_tolerance") != extraction_result.risk_tolerance:
                new_items["risk_tolerance"] = extraction_result.risk_tolerance
                changes["risk_tolerance"] = extraction_result.risk_tolerance

        # Process persona fields (Phase 1)
        if extraction_result.age is not None:
            if existing_profile.get("age") != extraction_result.age:
                new_items["age"] = extraction_result.age
                changes["age"] = extraction_result.age
                logger.info(f"[EXTRACTION] Age extracted: {extraction_result.age}")

        if extraction_result.relationship_status is not None:
            if existing_profile.get("relationship_status") != extraction_result.relationship_status:
                new_items["relationship_status"] = extraction_result.relationship_status
                changes["relationship_status"] = extraction_result.relationship_status

        if extraction_result.has_kids is not None:
            if existing_profile.get("has_kids") != extraction_result.has_kids:
                new_items["has_kids"] = extraction_result.has_kids
                changes["has_kids"] = extraction_result.has_kids

        if extraction_result.number_of_kids is not None:
            if existing_profile.get("number_of_kids") != extraction_result.number_of_kids:
                new_items["number_of_kids"] = extraction_result.number_of_kids
                changes["number_of_kids"] = extraction_result.number_of_kids

        if extraction_result.career is not None:
            if existing_profile.get("career") != extraction_result.career:
                new_items["career"] = extraction_result.career
                changes["career"] = extraction_result.career

        if extraction_result.location is not None:
            if existing_profile.get("location") != extraction_result.location:
                new_items["location"] = extraction_result.location
                changes["location"] = extraction_result.location

        # Process life aspiration fields (Phase 2)
        if extraction_result.marriage_plans is not None:
            if existing_profile.get("marriage_plans") != extraction_result.marriage_plans:
                new_items["marriage_plans"] = extraction_result.marriage_plans
                changes["marriage_plans"] = extraction_result.marriage_plans

        if extraction_result.family_plans is not None:
            if existing_profile.get("family_plans") != extraction_result.family_plans:
                new_items["family_plans"] = extraction_result.family_plans
                changes["family_plans"] = extraction_result.family_plans

        if extraction_result.career_goals is not None:
            if existing_profile.get("career_goals") != extraction_result.career_goals:
                new_items["career_goals"] = extraction_result.career_goals
                changes["career_goals"] = extraction_result.career_goals

        if extraction_result.retirement_age is not None:
            if existing_profile.get("retirement_age") != extraction_result.retirement_age:
                new_items["retirement_age"] = extraction_result.retirement_age
                changes["retirement_age"] = extraction_result.retirement_age

        if extraction_result.retirement_vision is not None:
            if existing_profile.get("retirement_vision") != extraction_result.retirement_vision:
                new_items["retirement_vision"] = extraction_result.retirement_vision
                changes["retirement_vision"] = extraction_result.retirement_vision

        if extraction_result.lifestyle_goals is not None:
            if existing_profile.get("lifestyle_goals") != extraction_result.lifestyle_goals:
                new_items["lifestyle_goals"] = extraction_result.lifestyle_goals
                changes["lifestyle_goals"] = extraction_result.lifestyle_goals

        # If we have new items, add them to the profile
        if new_items:
            # Use add_items() to ADD new data incrementally (not replace)
            updated_profile = None
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                updated_profile = await profile_repo.add_items(username, new_items)
            logger.info(f"[EXTRACTION] Profile updated for {username}, changes: {list(changes.keys())}")
            return {
                "changes": changes,
                "profile": updated_profile
            }

        logger.debug(f"[EXTRACTION] No changes detected for {username}")
        return None
    
    def _format_existing_profile(self, profile: Dict[str, Any]) -> str:
        """Format existing profile for agent context."""
        parts = []

        # Persona fields (Phase 1)
        if profile.get("age") is not None:
            parts.append(f"Age: {profile['age']}")

        if profile.get("relationship_status"):
            parts.append(f"Relationship status: {profile['relationship_status']}")

        if profile.get("has_kids") is not None:
            kids_str = "Has kids" if profile["has_kids"] else "No kids"
            if profile.get("number_of_kids"):
                kids_str += f" ({profile['number_of_kids']})"
            parts.append(kids_str)

        if profile.get("career"):
            parts.append(f"Career: {profile['career']}")

        if profile.get("location"):
            parts.append(f"Location: {profile['location']}")

        # Life aspirations (Phase 2)
        if profile.get("family_plans"):
            parts.append(f"Family plans: {profile['family_plans']}")

        if profile.get("retirement_age"):
            parts.append(f"Target retirement age: {profile['retirement_age']}")

        # Financial data
        if profile.get("goals"):
            goals_desc = [g.get("description", "Unknown goal") for g in profile["goals"]]
            parts.append(f"Goals already extracted: {', '.join(goals_desc)}")

        if profile.get("assets"):
            assets_desc = [f"{a.get('asset_type', 'asset')}: {a.get('description', 'Unknown')}" for a in profile["assets"]]
            parts.append(f"Assets already extracted: {', '.join(assets_desc)}")

        if profile.get("liabilities"):
            liabilities_desc = [f"{l.get('liability_type', 'liability')}: {l.get('description', 'Unknown')}" for l in profile["liabilities"]]
            parts.append(f"Liabilities already extracted: {', '.join(liabilities_desc)}")

        if profile.get("insurance"):
            insurance_desc = [i.get("insurance_type", "Unknown") for i in profile["insurance"]]
            parts.append(f"Insurance already extracted: {', '.join(insurance_desc)}")

        if profile.get("superannuation"):
            super_desc = [f"{s.get('fund_name', 'Unknown')}: ${s.get('balance', 0):,.2f}" for s in profile["superannuation"]]
            parts.append(f"Superannuation already extracted: {', '.join(super_desc)}")

        if profile.get("income") is not None:
            parts.append(f"Income: ${profile['income']:,.2f} annually")

        if profile.get("expenses") is not None:
            parts.append(f"Expenses: ${profile['expenses']:,.2f} monthly")

        if profile.get("risk_tolerance"):
            parts.append(f"Risk tolerance: {profile['risk_tolerance']}")

        return "\n".join(parts) if parts else "No existing profile data."
