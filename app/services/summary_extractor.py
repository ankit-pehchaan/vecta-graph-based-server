"""
Summary Extractor Service - Extract financial facts from conversation summaries.

Converts conversation summaries into structured financial data and updates the database.
Only updates fields that are not already populated to avoid overwriting user data.
"""

import json
import logging
from typing import Optional
from datetime import datetime, timezone
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.financial import Asset, Liability, Superannuation, Insurance
from app.core.config import settings

logger = logging.getLogger("summary_extractor")


class SummaryExtractor:
    """Service for extracting financial facts from conversation summaries."""
    
    def __init__(self):
        """Initialize the summary extractor with OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    async def extract_facts_from_summary(self, summary: str) -> dict:
        """
        Extract financial facts from conversation summary using LLM.
        
        Args:
            summary: The conversation summary text
            
        Returns:
            dict: Extracted financial facts
        """
        if not summary or not summary.strip():
            logger.warning("[EXTRACT] Empty summary provided")
            return {}
        
        prompt = f"""You are a financial information extractor. Extract ALL financial facts from the conversation summary.

CONVERSATION SUMMARY:
{summary}

Extract these fields if mentioned or implied:
- age (integer)
- marital_status (string: single/married/divorced/widowed) - ONLY if explicitly stated
- dependents (integer: number of dependents/children) - ONLY if explicitly stated as "has X children", "X dependents", "X kids", etc. DO NOT infer from mentions like "their son" or "for my daughter"
- annual_income (integer in dollars)
- monthly_income (integer - calculate from annual: annual/12)
- monthly_expenses (integer)
- savings (integer - total savings/cash, use 0 if they say "no savings")
- emergency_fund (integer - use 0 if they say "no emergency fund")
- debts (list of objects with type, amount, interest_rate, description OR empty list [] if "debt-free")
- life_insurance (string: "basic", "comprehensive", or coverage amount as number)
- private_health_insurance (string: "basic"/"bronze"/"silver"/"gold")
- superannuation (object with balance as number if mentioned)
- job_stability (string: "stable"/"casual"/"contract") - ONLY if explicitly stated

CRITICAL RULES:
1. ONLY extract values that are EXPLICITLY mentioned or can be calculated
2. DO NOT use "unsure", "unknown", "pending", "n/a", or similar placeholder values
3. If a field is not mentioned or unclear, DO NOT include it in the response
4. All numeric fields MUST be numbers (integers), not strings
5. For "debt-free" → debts: []
6. For "no savings" → savings: 0
7. For "no emergency fund" → emergency_fund: 0
8. Convert annual salary to monthly: divide by 12
9. For debts, include type, amount, interest_rate, description if available
10. DO NOT infer dependents from casual mentions - only extract if explicitly stated as a count

EXAMPLES:
- "annual salary of $300k" → annual_income: 300000, monthly_income: 25000
- "debt-free" → debts: []
- "$500k debt at 12% interest for 3 years" → debts: [{{"type": "loan", "amount": 500000, "interest_rate": 12, "description": "3 year loan"}}]
- "50k in savings" → savings: 50000
- "no savings" → savings: 0
- "I have 2 children" → dependents: 2
- "buying property for their son" → DO NOT extract dependents (not explicitly stated as count)
- "no dependents" or "no children" → dependents: 0

Respond with JSON containing ONLY fields with concrete values:"""

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "Extract financial facts. Respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            content = response.choices[0].message.content.strip()
            
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            extracted = json.loads(content)
            logger.info(f"[EXTRACT] Extracted {len(extracted)} fields from summary")
            return extracted
            
        except Exception as e:
            logger.error(f"[EXTRACT] Error extracting facts: {e}")
            return {}
    
    async def update_user_from_summary(
        self,
        session: AsyncSession,
        username: str,
        summary: str
    ) -> dict:
        """
        Extract facts from summary and update user in database.
        
        Args:
            session: SQLAlchemy async session
            username: User's email/username
            summary: Conversation summary text
            
        Returns:
            dict with update results
        """
        print(f"\n✅✅✅ [EXTRACTOR] ========== Starting extraction for {username} ==========")
        logger.info(f"[UPDATE] Processing summary for user: {username}")
        
        # Step 1: Extract facts from summary
        print(f"✅✅✅ [EXTRACTOR] Step 1: Extracting facts from summary...")
        facts = await self.extract_facts_from_summary(summary)
        
        if not facts:
            print(f"✅✅✅ [EXTRACTOR] No facts extracted from summary")
            logger.info("[UPDATE] No facts extracted from summary")
            return {"updates": [], "message": "No facts extracted"}
        
        print(f"✅✅✅ [EXTRACTOR] Extracted {len(facts)} fields: {list(facts.keys())}")
        print(f"✅✅✅ [EXTRACTOR] Extracted {facts}")
        
        # Step 2: Load user with relationships
        print(f"✅✅✅ [EXTRACTOR] Step 2: Loading user from database...")
        stmt = (
            select(User)
            .options(
                selectinload(User.assets),
                selectinload(User.liabilities),
                selectinload(User.superannuation),
                selectinload(User.insurance),
            )
            .where(User.email == username)
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"✅✅✅ [EXTRACTOR] ❌ User not found: {username}")
            logger.warning(f"[UPDATE] User not found: {username}")
            return {"updates": [], "message": f"User {username} not found"}
        
        print(f"✅✅✅ [EXTRACTOR] User loaded: {username}")
        
        # Step 3: Update user with extracted facts
        print(f"✅✅✅ [EXTRACTOR] Step 3: Updating user fields...")
        updates_made = await self._update_user_fields(session, user, facts)
        
        # Step 4: Calculate missing fields if required_fields exists
        if user.required_fields:
            print(f"✅✅✅ [EXTRACTOR] Step 4: Calculating missing fields...")
            await self._update_missing_fields(user)
            missing_count = len(user.missing_fields or [])
            required_count = len(user.required_fields)
            updates_made.append(f"missing_fields: {missing_count}/{required_count} remaining")
            print(f"✅✅✅ [EXTRACTOR] Missing fields: {missing_count}/{required_count}")
        
        # Step 5: Commit changes
        if updates_made:
            user.updated_at = datetime.now(timezone.utc)
            await session.commit()
            print(f"✅✅✅ [EXTRACTOR] ========== ✅ COMMITTED {len(updates_made)} UPDATES ==========")
            print(f"✅✅✅ [EXTRACTOR] Updates made:")
            for update in updates_made:
                print(f"✅✅✅ [EXTRACTOR]   ✓ {update}")
            logger.info(f"[UPDATE] Made {len(updates_made)} updates for {username}")
        else:
            print(f"✅✅✅ [EXTRACTOR] ========== No updates needed ==========")
        
        print(f"✅✅✅ [EXTRACTOR] ========== Extraction complete ==========\n")
        
        return {
            "updates": updates_made,
            "message": f"Updated {len(updates_made)} fields" if updates_made else "No updates needed"
        }
    
    async def _update_user_fields(
        self,
        session: AsyncSession,
        user: User,
        facts: dict
    ) -> list:
        """Update user fields from extracted facts."""
        updates_made = []
        
        # Invalid placeholder values to skip
        invalid_values = {"unsure", "pending", "unknown", "n/a", "none", "unconfirmed"}
        
        def is_valid_number(value):
            if isinstance(value, bool):
                return False
            return isinstance(value, (int, float))
        
        def is_valid_string(value):
            if not isinstance(value, str):
                return False
            return value.lower().strip() not in invalid_values
        
        # Field mappings: extracted_key -> (db_field, field_type)
        field_mappings = {
            "age": ("age", "int"),
            "dependents": ("dependents", "int"),
            "monthly_income": ("monthly_income", "float"),
            "monthly_expenses": ("expenses", "float"),
            "savings": ("savings", "float"),
            "annual_income": ("income", "float"),
            "marital_status": ("relationship_status", "string"),
            "job_stability": ("job_stability", "string"),
            "timeline": ("timeline", "string"),
        }
        
        # Update simple fields
        for fact_key, (db_field, field_type) in field_mappings.items():
            if fact_key in facts and facts[fact_key] is not None:
                value = facts[fact_key]
                
                # Validate based on field type
                if field_type in ("int", "float"):
                    if not is_valid_number(value):
                        print(f"✅✅✅ [EXTRACTOR]   ⏭️  Skipped {fact_key}: invalid value '{value}'")
                        continue
                    value = int(value) if field_type == "int" else float(value)
                elif field_type == "string":
                    if not is_valid_string(value):
                        print(f"✅✅✅ [EXTRACTOR]   ⏭️  Skipped {fact_key}: invalid value '{value}'")
                        continue
                
                # Only update if not already set
                current_value = getattr(user, db_field)
                if current_value is None:
                    setattr(user, db_field, value)
                    updates_made.append(f"{fact_key}: {value}")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated {fact_key} = {value}")
                else:
                    print(f"✅✅✅ [EXTRACTOR]   ⏭️  Skipped {fact_key}: already set to {current_value}")
        
        # Handle savings -> Asset table (always sync)
        if "savings" in facts and is_valid_number(facts["savings"]):
            savings_value = float(facts["savings"])
            existing_savings = next((a for a in (user.assets or []) if a.asset_type == "savings"), None)
            
            if existing_savings:
                if existing_savings.value != savings_value:
                    existing_savings.value = savings_value
                    updates_made.append(f"savings_asset: ${savings_value} (updated)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated savings_asset = ${savings_value}")
                else:
                    print(f"✅✅✅ [EXTRACTOR]   ⏭️  Skipped savings_asset: already ${savings_value}")
            else:
                new_asset = Asset(
                    user_id=user.id,
                    asset_type="savings",
                    description="Cash Savings",
                    value=savings_value,
                )
                session.add(new_asset)
                updates_made.append(f"savings_asset: ${savings_value} (created)")
                print(f"✅✅✅ [EXTRACTOR]   ✓ Created savings_asset = ${savings_value}")
        
        # Handle emergency_fund -> Asset table
        if "emergency_fund" in facts and is_valid_number(facts["emergency_fund"]):
            ef_value = float(facts["emergency_fund"])
            existing_ef = next((a for a in (user.assets or []) if a.asset_type == "emergency_fund"), None)
            
            if existing_ef:
                if existing_ef.value != ef_value:
                    existing_ef.value = ef_value
                    updates_made.append(f"emergency_fund: ${ef_value} (updated)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated emergency_fund = ${ef_value}")
                else:
                    print(f"✅✅✅ [EXTRACTOR]   ⏭️  Skipped emergency_fund: already ${ef_value}")
            else:
                new_asset = Asset(
                    user_id=user.id,
                    asset_type="emergency_fund",
                    description="Emergency Fund",
                    value=ef_value,
                )
                session.add(new_asset)
                updates_made.append(f"emergency_fund: ${ef_value} (created)")
                print(f"✅✅✅ [EXTRACTOR]   ✓ Created emergency_fund = ${ef_value}")
        
        # Handle debts -> Liability table
        if "debts" in facts and isinstance(facts["debts"], list):
            for debt in facts["debts"]:
                if isinstance(debt, dict) and is_valid_number(debt.get("amount")):
                    debt_type = debt.get("type", "other")
                    debt_amount = float(debt.get("amount"))
                    
                    existing_liability = next(
                        (l for l in (user.liabilities or []) if l.liability_type == debt_type),
                        None
                    )
                    
                    if existing_liability:
                        existing_liability.amount = debt_amount
                        if is_valid_number(debt.get("interest_rate")):
                            existing_liability.interest_rate = float(debt.get("interest_rate"))
                        updates_made.append(f"debt: {debt_type} ${debt_amount} (updated)")
                        print(f"✅✅✅ [EXTRACTOR]   ✓ Updated debt: {debt_type} = ${debt_amount}")
                    else:
                        liability = Liability(
                            user_id=user.id,
                            liability_type=debt_type,
                            description=debt.get("description", ""),
                            amount=debt_amount,
                            interest_rate=float(debt.get("interest_rate")) if is_valid_number(debt.get("interest_rate")) else None,
                        )
                        session.add(liability)
                        updates_made.append(f"debt: {debt_type} ${debt_amount} (created)")
                        print(f"✅✅✅ [EXTRACTOR]   ✓ Created debt: {debt_type} = ${debt_amount}")
        
        # Handle superannuation -> Superannuation table
        if "superannuation" in facts:
            super_data = facts["superannuation"]
            if isinstance(super_data, dict) and is_valid_number(super_data.get("balance")):
                super_balance = float(super_data["balance"])
                
                if user.superannuation and len(user.superannuation) > 0:
                    user.superannuation[0].balance = super_balance
                    updates_made.append(f"superannuation: ${super_balance} (updated)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated superannuation = ${super_balance}")
                else:
                    new_super = Superannuation(
                        user_id=user.id,
                        fund_name="Primary Super",
                        balance=super_balance,
                    )
                    session.add(new_super)
                    updates_made.append(f"superannuation: ${super_balance} (created)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Created superannuation = ${super_balance}")
        
        # Handle life insurance -> Insurance table
        if "life_insurance" in facts and facts["life_insurance"]:
            coverage = facts["life_insurance"]
            if not (isinstance(coverage, str) and coverage.lower() in invalid_values):
                existing_life_ins = next(
                    (i for i in (user.insurance or []) if i.insurance_type == "life"),
                    None
                )
                
                if existing_life_ins:
                    if is_valid_number(coverage):
                        existing_life_ins.coverage_amount = float(coverage)
                    else:
                        existing_life_ins.provider = coverage
                    updates_made.append(f"life_insurance: {coverage} (updated)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated life_insurance = {coverage}")
                else:
                    ins = Insurance(
                        user_id=user.id,
                        insurance_type="life",
                        coverage_amount=float(coverage) if is_valid_number(coverage) else None,
                        provider=coverage if isinstance(coverage, str) else None,
                    )
                    session.add(ins)
                    updates_made.append(f"life_insurance: {coverage} (created)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Created life_insurance = {coverage}")
        
        # Handle health insurance -> Insurance table
        if "private_health_insurance" in facts and facts["private_health_insurance"]:
            health_value = facts["private_health_insurance"]
            if not (isinstance(health_value, str) and health_value.lower() in invalid_values):
                existing_health_ins = next(
                    (i for i in (user.insurance or []) if i.insurance_type == "health"),
                    None
                )
                
                if existing_health_ins:
                    existing_health_ins.provider = str(health_value)
                    updates_made.append(f"health_insurance: {health_value} (updated)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Updated health_insurance = {health_value}")
                else:
                    ins = Insurance(
                        user_id=user.id,
                        insurance_type="health",
                        provider=str(health_value),
                    )
                    session.add(ins)
                    updates_made.append(f"health_insurance: {health_value} (created)")
                    print(f"✅✅✅ [EXTRACTOR]   ✓ Created health_insurance = {health_value}")
        
        return updates_made
    
    async def _update_missing_fields(self, user: User) -> None:
        """Calculate and update missing fields based on required_fields."""
        required_fields = user.required_fields or []
        
        if not required_fields:
            return
        
        # Map field names to user attributes
        field_mapping = {
            "age": user.age,
            "monthly_income": user.monthly_income,
            "monthly_expenses": user.expenses,
            "emergency_fund": user.emergency_fund,
            "debts": user.liabilities,
            "superannuation": user.superannuation,
            "savings": user.savings,
            "timeline": user.timeline,
            "job_stability": user.job_stability,
            "marital_status": user.relationship_status,
            "dependents": user.dependents,
            "life_insurance": any(i.insurance_type == "life" for i in (user.insurance or [])),
            "private_health_insurance": any(i.insurance_type == "health" for i in (user.insurance or [])),
            "investments": user.assets,
        }
        
        # Check which fields are populated
        populated_fields = []
        for field in required_fields:
            value = field_mapping.get(field)
            
            if value is not None:
                if isinstance(value, list):
                    if len(value) > 0:
                        populated_fields.append(field)
                elif isinstance(value, bool):
                    if value:
                        populated_fields.append(field)
                elif isinstance(value, (str, int, float)):
                    populated_fields.append(field)
        
        # Calculate missing fields
        missing_fields = list(set(required_fields) - set(populated_fields))
        user.missing_fields = missing_fields
        
        # Update conversation phase based on missing fields
        if not missing_fields:
            user.conversation_phase = "planning"
        elif len(missing_fields) > 0:
            user.conversation_phase = "assessment"
        
        logger.debug(f"[MISSING_FIELDS] Required: {len(required_fields)}, Missing: {len(missing_fields)}")
