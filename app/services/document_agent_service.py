
import os
import uuid
from typing import Optional, Dict, Any, List, AsyncGenerator
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from sqlalchemy import select
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.services.agno_db import agno_db
from app.utils.document_parser import DocumentParser
from app.schemas.advice import DocumentProcessing, DocumentExtraction
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.repositories.user_repository import UserRepository
from app.models.user_kms import UserKmsMapping
from app.core.config import settings


# Reuse extraction models from profile_extractor
class ExtractedGoal(BaseModel):
    """A financial goal extracted from document."""
    description: str = Field(..., description="Description of the goal")
    amount: Optional[float] = Field(default=None, description="Target amount in AUD if mentioned")
    timeline_years: Optional[float] = Field(default=None, description="Timeline in years if mentioned")
    priority: Optional[str] = Field(default=None, description="Priority: High, Medium, or Low")


class ExtractedAsset(BaseModel):
    """An asset extracted from document."""
    asset_type: str = Field(..., description="Type: cash, savings, shares, managed_funds, property, investment_property, term_deposits, bonds, crypto, other")
    description: str = Field(..., description="Description of the asset")
    value: Optional[float] = Field(default=None, description="Value in AUD if mentioned")
    institution: Optional[str] = Field(default=None, description="Institution name if mentioned")


class ExtractedLiability(BaseModel):
    """A liability extracted from document."""
    liability_type: str = Field(..., description="Type: home_loan, car_loan, personal_loan, credit_card, investment_loan, hecs, other")
    description: str = Field(..., description="Description of the liability")
    amount: Optional[float] = Field(default=None, description="Outstanding balance in AUD if mentioned")
    monthly_payment: Optional[float] = Field(default=None, description="Monthly payment if mentioned")
    interest_rate: Optional[float] = Field(default=None, description="Interest rate if mentioned")


class ExtractedInsurance(BaseModel):
    """Insurance policy extracted from document."""
    insurance_type: str = Field(..., description="Type: life, health, income_protection, tpd, trauma, home, car, other")
    provider: Optional[str] = Field(default=None, description="Insurance provider if mentioned")
    coverage_amount: Optional[float] = Field(default=None, description="Coverage amount in AUD if mentioned")


class ExtractedSuperannuation(BaseModel):
    """Superannuation fund extracted from document."""
    fund_name: str = Field(default="Primary Super Fund", description="Name of the super fund if mentioned")
    balance: Optional[float] = Field(default=None, description="Super balance in AUD if mentioned")
    employer_contribution_rate: Optional[float] = Field(default=None, description="Employer contribution percentage if mentioned")
    personal_contribution_rate: Optional[float] = Field(default=None, description="Personal contribution percentage if mentioned")
    investment_option: Optional[str] = Field(default=None, description="Investment option: Balanced, Growth, Conservative, High Growth")
    insurance_death: Optional[float] = Field(default=None, description="Death cover amount within super")
    insurance_tpd: Optional[float] = Field(default=None, description="TPD cover amount within super")


class DocumentExtractionResult(BaseModel):
    """Structured output from document extraction agent."""
    goals: Optional[List[ExtractedGoal]] = Field(default_factory=list, description="Financial goals found in document")
    assets: Optional[List[ExtractedAsset]] = Field(default_factory=list, description="Assets found in document")
    liabilities: Optional[List[ExtractedLiability]] = Field(default_factory=list, description="Debts/loans found in document")
    insurance: Optional[List[ExtractedInsurance]] = Field(default_factory=list, description="Insurance policies found in document")
    superannuation: Optional[List[ExtractedSuperannuation]] = Field(default_factory=list, description="Superannuation funds found in document")
    income: Optional[float] = Field(default=None, description="Annual income found (in AUD)")
    monthly_income: Optional[float] = Field(default=None, description="Monthly income found (in AUD)")
    expenses: Optional[float] = Field(default=None, description="Monthly expenses found (in AUD)")
    summary: str = Field(..., description="Human-readable summary of what was found in the document, formatted for chat display")


# Document type specific prompts
DOCUMENT_PROMPTS = {
    "bank_statement": """Analyze this bank statement. Extract:
- Regular income deposits (salary, wages) - look for recurring credits
- Monthly expenses - calculate average from debits
- Account balances (as cash/savings assets)
- Any loan repayments visible (as liabilities with monthly_payment)
- Identify the bank/institution

Look for patterns in transactions to identify:
- Salary deposits (usually similar amounts, bi-weekly or monthly)
- Rent/mortgage payments
- Utility bills
- Insurance premiums
- Superannuation contributions""",

    "tax_return": """Analyze this tax return document. Extract:
- Gross and net annual income
- Any investment income (dividends, rental income)
- Deductions that indicate regular expenses
- HECS/HELP debt if mentioned (as liability)
- Superannuation contributions
- Any assets mentioned (rental properties, shares)
- Tax bracket indicators for risk tolerance assessment""",

    "investment_statement": """Analyze this investment statement. Extract:
- Fund/account name and provider
- Current balance/value as an asset
- Investment type (shares, managed_fund, ETF, term_deposit)
- Any fees or expenses
- Performance information if available
- For super statements: extract as superannuation with insurance details if present""",

    "payslip": """Analyze this payslip. Extract:
- Gross and net salary (calculate annual from pay period)
- Superannuation contributions (employer and personal)
- Tax withheld
- Any salary sacrifice arrangements
- Employer name/institution
- HECS/HELP deductions if present (indicates HECS liability)""",

    "default": """Analyze this financial document. Extract any financial information including:
- Income (annual or monthly)
- Assets (savings, investments, property)
- Liabilities (loans, debts, credit cards)
- Insurance policies
- Superannuation/retirement funds
- Regular expenses"""
}


class DocumentAgentService:
    """Process documents and extract financial data using LLM agent."""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._agents: dict[str, Agent] = {}
        self.document_parser = DocumentParser()
        self._pending_extractions: dict[str, dict] = {}  # Track pending confirmations
        self._db_dir = "tmp/agents"

        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)

        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    async def _get_user_kms_key(self, username: str) -> Optional[str]:
        """
        Fetch user's KMS key ARN from database.

        Args:
            username: User's email/username

        Returns:
            KMS key ARN or None if not found
        """
        async for session in self.db_manager.get_session():
            # First get user ID from username (email)
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)

            if not user or 'id' not in user:
                print(f"[DocumentAgent] User not found: {username}")
                return None

            user_id = user['id']

            # Get KMS mapping
            result = await session.execute(
                select(UserKmsMapping).where(UserKmsMapping.user_id == user_id)
            )
            kms_mapping = result.scalar_one_or_none()

            if kms_mapping:
                print(f"[DocumentAgent] Found KMS key for user {user_id}")
                return kms_mapping.kms_key_arn

            print(f"[DocumentAgent] No KMS key found for user {user_id}")
            return None

    def _get_document_agent(self, username: str) -> Agent:
        """Get or create document analysis agent for user."""
        if username in self._agents:
            return self._agents[username]

        db_file = os.path.join(self._db_dir, f"document_agent_{username}.db")

        agent = Agent(
            name="Financial Document Analyzer",
            model=OpenAIChat(id="gpt-4o"),
            instructions="""You are a financial document analysis specialist. Your job is to extract financial information from documents and provide a clear summary.

EXTRACTION RULES:
1. Extract only what is clearly stated in the document - don't infer
2. All monetary values should be in Australian Dollars (AUD)
3. For assets: identify type (cash, savings, shares, property, etc.) and value
4. For liabilities: identify type (home_loan, car_loan, credit_card, hecs, etc.), amount, and monthly payment if visible
5. For income: determine if annual or monthly and convert appropriately
6. For superannuation: extract fund name, balance, contribution rates, and any insurance within super

SUMMARY FORMAT:
Create a friendly, conversational summary that:
- Highlights the key financial information found
- Uses simple language (not technical jargon)
- Groups related items together
- Mentions any notable patterns or observations
- Is suitable for display in a chat interface

Example summary style:
"I've analyzed your NAB bank statement. Here's what I found:

Income: You have regular deposits of $4,250 every fortnight, suggesting an annual salary around $110,500.

Savings: Your closing balance shows $23,450 in savings.

Expenses: Your average monthly spending is about $3,800, with the largest categories being rent ($1,800) and groceries (~$600).

I also noticed regular transfers to a home loan account of $2,100/month."
""",
            db=agno_db(db_file),
            user_id=f"{username}_document",
            output_schema=DocumentExtractionResult,
            markdown=False,
            debug_mode=False
        )

        self._agents[username] = agent
        return agent

    async def process_document(
        self,
        username: str,
        s3_url: str,
        document_type: str,
        filename: str
    ) -> AsyncGenerator[dict, None]:
        """
        Process document and yield status updates.

        Yields:
            DocumentProcessing status updates, then final DocumentExtraction
        """
        now = lambda: datetime.now(timezone.utc).isoformat()

        # Fetch user's KMS key for decryption
        kms_key_arn = await self._get_user_kms_key(username)
        if not kms_key_arn:
            yield DocumentProcessing(
                status="error",
                message="Could not find encryption key for your account. Please contact support.",
                timestamp=now()
            ).model_dump()
            return

        # Status: downloading
        yield DocumentProcessing(
            status="downloading",
            message=f"Downloading and decrypting {filename}...",
            timestamp=now()
        ).model_dump()

        try:
            # Download, decrypt, and parse document
            document_text, file_type = await self.document_parser.download_and_parse(
                s3_url,
                kms_key_arn=kms_key_arn
            )

            if not document_text.strip():
                yield DocumentProcessing(
                    status="error",
                    message="The document appears to be empty or could not be read.",
                    timestamp=now()
                ).model_dump()
                return

        except ValueError as e:
            yield DocumentProcessing(
                status="error",
                message=str(e),
                timestamp=now()
            ).model_dump()
            return
        except Exception as e:
            yield DocumentProcessing(
                status="error",
                message=f"Failed to process document: {str(e)}",
                timestamp=now()
            ).model_dump()
            return

        # Status: parsing
        yield DocumentProcessing(
            status="parsing",
            message="Extracting text content...",
            timestamp=now()
        ).model_dump()

        # Status: analyzing
        yield DocumentProcessing(
            status="analyzing",
            message="Analyzing financial information...",
            timestamp=now()
        ).model_dump()

        try:
            # Get document-type specific prompt
            doc_prompt = DOCUMENT_PROMPTS.get(document_type, DOCUMENT_PROMPTS["default"])

            # Build full prompt
            prompt = f"""{doc_prompt}

DOCUMENT CONTENT:
{document_text[:15000]}  # Limit to avoid token limits

Please extract all financial information and provide a summary."""

            # Run agent
            agent = self._get_document_agent(username)
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            # Parse result
            if hasattr(response, 'content') and isinstance(response.content, DocumentExtractionResult):
                extraction_result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                extraction_result = DocumentExtractionResult(**response.content)
            else:
                yield DocumentProcessing(
                    status="error",
                    message="Could not extract financial data from document.",
                    timestamp=now()
                ).model_dump()
                return

            # Generate extraction ID and store pending extraction
            extraction_id = str(uuid.uuid4())
            self._pending_extractions[extraction_id] = {
                "username": username,
                "extraction_result": extraction_result,
                "document_type": document_type,
                "filename": filename,
                "created_at": now()
            }

            # Convert extraction result to dict for response
            extracted_data = {
                "goals": [g.model_dump() for g in (extraction_result.goals or [])],
                "assets": [a.model_dump() for a in (extraction_result.assets or [])],
                "liabilities": [l.model_dump() for l in (extraction_result.liabilities or [])],
                "insurance": [i.model_dump() for i in (extraction_result.insurance or [])],
                "superannuation": [s.model_dump() for s in (extraction_result.superannuation or [])],
                "income": extraction_result.income,
                "monthly_income": extraction_result.monthly_income,
                "expenses": extraction_result.expenses
            }

            # Yield extraction result
            yield DocumentExtraction(
                extraction_id=extraction_id,
                summary=extraction_result.summary,
                extracted_data=extracted_data,
                document_type=document_type,
                requires_confirmation=True,
                timestamp=now()
            ).model_dump()

        except Exception as e:
            print(f"Error in document analysis: {e}")
            import traceback
            traceback.print_exc()
            yield DocumentProcessing(
                status="error",
                message=f"Analysis failed: {str(e)}",
                timestamp=now()
            ).model_dump()

    async def confirm_extraction(
        self,
        username: str,
        extraction_id: str,
        confirmed: bool,
        corrections: Optional[dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Confirm or reject an extraction.

        Returns:
            Profile update result if confirmed, None otherwise
        """
        # Get pending extraction
        pending = self._pending_extractions.get(extraction_id)
        if not pending:
            print(f"[DocumentAgent] Extraction {extraction_id} not found")
            return None

        if pending["username"] != username:
            print(f"[DocumentAgent] Username mismatch for extraction {extraction_id}")
            return None

        # Remove from pending
        del self._pending_extractions[extraction_id]

        if not confirmed:
            print(f"[DocumentAgent] Extraction {extraction_id} rejected by user")
            return None

        extraction_result: DocumentExtractionResult = pending["extraction_result"]

        # Apply corrections if provided
        if corrections:
            # User can provide corrections to specific fields
            for field, value in corrections.items():
                if hasattr(extraction_result, field):
                    setattr(extraction_result, field, value)

        # Build new_items dictionary for add_items()
        new_items = {}
        changes = {}
        now = datetime.now(timezone.utc).isoformat()

        def to_dict(item):
            if hasattr(item, 'model_dump'):
                return item.model_dump()
            return item

        # Process goals
        if extraction_result.goals and len(extraction_result.goals) > 0:
            goals_list = []
            for g in extraction_result.goals:
                goal_dict = to_dict(g)
                goal_dict["created_at"] = now
                goals_list.append(goal_dict)
            new_items["goals"] = goals_list
            changes["goals"] = goals_list

        # Process assets
        if extraction_result.assets and len(extraction_result.assets) > 0:
            assets_list = []
            for a in extraction_result.assets:
                asset_dict = to_dict(a)
                asset_dict["created_at"] = now
                assets_list.append(asset_dict)
            new_items["assets"] = assets_list
            changes["assets"] = assets_list

        # Process liabilities
        if extraction_result.liabilities and len(extraction_result.liabilities) > 0:
            liabilities_list = []
            for l in extraction_result.liabilities:
                liability_dict = to_dict(l)
                liability_dict["created_at"] = now
                liabilities_list.append(liability_dict)
            new_items["liabilities"] = liabilities_list
            changes["liabilities"] = liabilities_list

        # Process insurance
        if extraction_result.insurance and len(extraction_result.insurance) > 0:
            insurance_list = []
            for i in extraction_result.insurance:
                insurance_dict = to_dict(i)
                insurance_dict["created_at"] = now
                insurance_list.append(insurance_dict)
            new_items["insurance"] = insurance_list
            changes["insurance"] = insurance_list

        # Process superannuation
        if extraction_result.superannuation and len(extraction_result.superannuation) > 0:
            super_list = []
            for s in extraction_result.superannuation:
                super_dict = to_dict(s)
                super_dict["created_at"] = now
                super_dict["updated_at"] = now
                super_list.append(super_dict)
            new_items["superannuation"] = super_list
            changes["superannuation"] = super_list

        # Process scalar fields
        if extraction_result.income is not None:
            new_items["income"] = extraction_result.income
            changes["income"] = extraction_result.income

        if extraction_result.monthly_income is not None:
            new_items["monthly_income"] = extraction_result.monthly_income
            changes["monthly_income"] = extraction_result.monthly_income

        if extraction_result.expenses is not None:
            new_items["expenses"] = extraction_result.expenses
            changes["expenses"] = extraction_result.expenses

        # Update profile if we have items
        if new_items:
            updated_profile = None
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                updated_profile = await profile_repo.add_items(username, new_items)

            print(f"[DocumentAgent] Profile updated for {username}, changes: {list(changes.keys())}")
            return {
                "changes": changes,
                "profile": updated_profile
            }

        print(f"[DocumentAgent] No changes to apply for {username}")
        return None
