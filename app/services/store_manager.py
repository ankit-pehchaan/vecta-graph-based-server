"""Store Manager - PostgreSQL wrapper for conversation state management.

This adapts the SQLite-based StoreManager pattern from vecta-financial-educator-main
to use the existing PostgreSQL repositories.
"""
from typing import Optional, Any
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.financial import Asset, Liability, Superannuation


class StoreManager:
    """Manages the central store for user financial data using PostgreSQL.

    Provides the same interface as the SQLite StoreManager but uses
    the existing PostgreSQL User model and related tables.
    """

    def __init__(self, session: AsyncSession, session_id: str):
        """
        Initialize StoreManager.

        Args:
            session: SQLAlchemy async session
            session_id: User identifier (email)
        """
        self._session = session
        self.session_id = session_id

    def _get_empty_store(self) -> dict:
        """Returns an empty store structure matching the source format."""
        return {
            # Goal info
            "user_goal": None,
            "goal_classification": None,
            "stated_goals": [],
            "discovered_goals": [],
            "critical_concerns": [],
            "all_goals": [],

            # User profile
            "age": None,
            "monthly_income": None,
            "monthly_expenses": None,
            "savings": None,
            "emergency_fund": None,
            "debts": [],
            "investments": [],
            "marital_status": None,
            "dependents": None,
            "job_stability": None,
            "life_insurance": None,
            "private_health_insurance": None,
            "superannuation": {
                "balance": None,
                "employer_contribution": 11.5,
                "voluntary_contribution": None
            },
            "hecs_debt": None,

            # Goal-specific
            "timeline": None,
            "target_amount": None,

            # System fields
            "required_fields": [],
            "missing_fields": [],
            "risk_profile": None,
            "conversation_phase": "initial",
            "pending_probe": None
        }

    async def _get_user(self) -> Optional[User]:
        """Get user model with all relationships loaded."""
        stmt = (
            select(User)
            .options(
                selectinload(User.goals),
                selectinload(User.assets),
                selectinload(User.liabilities),
                selectinload(User.insurance),
                selectinload(User.superannuation),
            )
            .where(User.email == self.session_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_store(self) -> dict:
        """Load the current store from PostgreSQL."""
        user = await self._get_user()

        if not user:
            return self._get_empty_store()

        # Build debts list from liabilities
        debts = []
        for liability in user.liabilities or []:
            debts.append({
                "type": liability.liability_type,
                "description": liability.description,
                "amount": liability.amount,
                "interest_rate": liability.interest_rate,
                "monthly_payment": liability.monthly_payment,
            })

        # Build investments list from assets (excluding savings/emergency_fund)
        investments = []
        savings_total = 0.0
        emergency_fund_total = 0.0
        for asset in user.assets or []:
            if asset.asset_type == "savings":
                savings_total += asset.value or 0
            elif asset.asset_type == "emergency_fund":
                emergency_fund_total += asset.value or 0
            else:
                investments.append({
                    "type": asset.asset_type,
                    "description": asset.description,
                    "value": asset.value,
                })

        # Build superannuation from related records
        super_balance = 0.0
        voluntary_contribution = None
        for super_record in user.superannuation or []:
            super_balance += super_record.balance or 0
            if super_record.personal_contribution_rate:
                voluntary_contribution = super_record.personal_contribution_rate

        # Check insurance types
        life_insurance = None
        private_health_insurance = None
        for ins in user.insurance or []:
            if ins.insurance_type == "life":
                life_insurance = ins.coverage_amount
            elif ins.insurance_type == "health":
                private_health_insurance = True

        # Map relationship_status to marital_status for source compatibility
        marital_status = user.relationship_status

        return {
            # Goal info
            "user_goal": user.user_goal,
            "goal_classification": user.goal_classification,
            "stated_goals": user.stated_goals or [],
            "discovered_goals": user.discovered_goals or [],
            "critical_concerns": user.critical_concerns or [],
            "all_goals": (user.stated_goals or []) + [
                g.get("goal") for g in (user.discovered_goals or []) if g.get("goal")
            ],

            # User profile
            "age": user.age,
            "monthly_income": user.monthly_income,
            "monthly_expenses": user.expenses,
            "savings": savings_total if savings_total > 0 else None,  # Computed from Assets table
            "emergency_fund": emergency_fund_total if emergency_fund_total > 0 else None,
            "debts": debts,
            "investments": investments,
            "marital_status": marital_status,
            "dependents": user.dependents if user.dependents is not None else (user.number_of_kids if user.has_kids else 0),
            "job_stability": user.job_stability,
            "life_insurance": life_insurance,
            "private_health_insurance": private_health_insurance,
            "superannuation": {
                "balance": super_balance if super_balance > 0 else None,
                "employer_contribution": 11.5,
                "voluntary_contribution": voluntary_contribution
            },
            "hecs_debt": None,  # TODO: Extract from liabilities if type is "hecs"

            # Goal-specific
            "timeline": user.timeline,
            "target_amount": user.target_amount,

            # System fields
            "required_fields": user.required_fields or [],
            "missing_fields": user.missing_fields or [],
            "risk_profile": user.risk_profile,
            "conversation_phase": user.conversation_phase or "initial",
            "pending_probe": user.pending_probe
        }

    async def update_store(self, updates: dict) -> dict:
        """Update specific fields in the store."""
        user = await self._get_user()

        if not user:
            raise ValueError(f"User with email {self.session_id} not found")

        # Map updates to User model fields
        field_mapping = {
            "user_goal": "user_goal",
            "goal_classification": "goal_classification",
            "conversation_phase": "conversation_phase",
            "stated_goals": "stated_goals",
            "discovered_goals": "discovered_goals",
            "critical_concerns": "critical_concerns",
            "required_fields": "required_fields",
            "missing_fields": "missing_fields",
            "pending_probe": "pending_probe",
            "risk_profile": "risk_profile",
            "age": "age",
            "monthly_income": "monthly_income",
            "monthly_expenses": "expenses",
            "savings": "savings",
            # emergency_fund moved to Asset table - handled separately below
            "marital_status": "relationship_status",
            "dependents": "dependents",
            "job_stability": "job_stability",
            "timeline": "timeline",
            "target_amount": "target_amount",
        }

        for source_key, target_key in field_mapping.items():
            if source_key in updates:
                setattr(user, target_key, updates[source_key])

        # Handle savings -> Asset table (for cash_balance calculation)
        if "savings" in updates and updates["savings"]:
            savings_value = updates["savings"]
            existing_savings = None
            for asset in user.assets or []:
                if asset.asset_type == "savings":
                    existing_savings = asset
                    break

            if existing_savings:
                existing_savings.value = savings_value
            else:
                new_savings_asset = Asset(
                    user_id=user.id,
                    asset_type="savings",
                    description="Cash Savings",
                    value=savings_value,
                )
                self._session.add(new_savings_asset)

        # Handle emergency_fund -> Asset table (normalized storage)
        if "emergency_fund" in updates and updates["emergency_fund"]:
            emergency_fund_value = updates["emergency_fund"]
            # Check if emergency_fund asset already exists
            existing_ef = None
            for asset in user.assets or []:
                if asset.asset_type == "emergency_fund":
                    existing_ef = asset
                    break

            if existing_ef:
                existing_ef.value = emergency_fund_value
            else:
                new_ef_asset = Asset(
                    user_id=user.id,
                    asset_type="emergency_fund",
                    description="Emergency Fund",
                    value=emergency_fund_value,
                )
                self._session.add(new_ef_asset)

        # Handle superannuation updates specially
        if "superannuation" in updates and isinstance(updates["superannuation"], dict):
            super_update = updates["superannuation"]
            if super_update.get("balance") is not None:
                # Update or create superannuation record
                if user.superannuation:
                    user.superannuation[0].balance = super_update["balance"]
                else:
                    from app.models.financial import Superannuation as SuperModel
                    new_super = SuperModel(
                        user_id=user.id,
                        fund_name="Primary Super",
                        balance=super_update["balance"],
                        employer_contribution_rate=super_update.get("employer_contribution", 11.5),
                        personal_contribution_rate=super_update.get("voluntary_contribution"),
                    )
                    self._session.add(new_super)

        # Handle debts updates (add new liabilities)
        if "debts" in updates and isinstance(updates["debts"], list):
            from app.models.financial import Liability
            for debt in updates["debts"]:
                if isinstance(debt, dict):
                    liability = Liability(
                        user_id=user.id,
                        liability_type=debt.get("type", "other"),
                        description=debt.get("description", ""),
                        amount=debt.get("amount"),
                        interest_rate=debt.get("interest_rate"),
                        monthly_payment=debt.get("monthly_payment"),
                    )
                    self._session.add(liability)

        # Handle insurance updates
        if "life_insurance" in updates and updates["life_insurance"]:
            from app.models.financial import Insurance
            ins = Insurance(
                user_id=user.id,
                insurance_type="life",
                coverage_amount=updates["life_insurance"] if isinstance(updates["life_insurance"], (int, float)) else None,
            )
            self._session.add(ins)

        if "private_health_insurance" in updates and updates["private_health_insurance"]:
            from app.models.financial import Insurance
            ins = Insurance(
                user_id=user.id,
                insurance_type="health",
            )
            self._session.add(ins)

        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

        return await self.get_store()

    async def add_discovered_goal(self, goal: dict) -> dict:
        """Add a goal that was discovered during assessment."""
        user = await self._get_user()
        if not user:
            raise ValueError(f"User with email {self.session_id} not found")

        discovered_goals = user.discovered_goals or []
        discovered_goals.append(goal)
        user.discovered_goals = discovered_goals
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

        return await self.get_store()

    async def add_critical_concern(self, concern: dict) -> dict:
        """Add a critical concern that user denied but needs to be addressed."""
        user = await self._get_user()
        if not user:
            raise ValueError(f"User with email {self.session_id} not found")

        critical_concerns = user.critical_concerns or []
        critical_concerns.append(concern)
        user.critical_concerns = critical_concerns
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

        return await self.get_store()

    async def add_stated_goal(self, goal: str) -> dict:
        """Add a goal that user stated upfront."""
        user = await self._get_user()
        if not user:
            raise ValueError(f"User with email {self.session_id} not found")

        stated_goals = user.stated_goals or []
        if goal not in stated_goals:
            stated_goals.append(goal)
        user.stated_goals = stated_goals
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

        return await self.get_store()

    async def reset_store(self) -> None:
        """Reset conversation state (not financial data)."""
        user = await self._get_user()
        if not user:
            return

        # Reset only conversation state fields
        user.user_goal = None
        user.goal_classification = None
        user.conversation_phase = "initial"
        user.stated_goals = None
        user.discovered_goals = None
        user.critical_concerns = None
        user.required_fields = None
        user.missing_fields = None
        user.pending_probe = None
        user.risk_profile = None
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def get_field(self, field_name: str) -> Optional[Any]:
        """Get a specific field value from store."""
        store = await self.get_store()
        return store.get(field_name)

    async def set_field(self, field_name: str, value: Any) -> dict:
        """Set a specific field value in store."""
        return await self.update_store({field_name: value})
