"""Financial profile repository implementation using PostgreSQL."""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.interfaces.financial_profile import IFinancialProfileRepository
from app.models.user import User
from app.models.financial import Goal, Asset, Liability, Insurance, Superannuation


class FinancialProfileRepository(IFinancialProfileRepository):
    """PostgreSQL implementation of financial profile repository.
    
    Financial data is now stored on the User model with related tables
    for goals, assets, liabilities, insurance, and superannuation.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a financial profile by user email."""
        user = await self._get_user_with_financial_data(email)
        return user.to_financial_dict() if user else None

    async def get_by_user_id(self, user_id: int) -> Optional[dict]:
        """Retrieve a financial profile by user ID."""
        stmt = (
            select(User)
            .options(
                selectinload(User.goals),
                selectinload(User.assets),
                selectinload(User.liabilities),
                selectinload(User.insurance),
                selectinload(User.superannuation),
            )
            .where(User.id == user_id)
        )
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()
        return user.to_financial_dict() if user else None

    async def _get_user_with_financial_data(self, email: str) -> Optional[User]:
        """Get user model with all financial relationships loaded."""
        stmt = (
            select(User)
            .options(
                selectinload(User.goals),
                selectinload(User.assets),
                selectinload(User.liabilities),
                selectinload(User.insurance),
                selectinload(User.superannuation),
            )
            .where(User.email == email)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data to an existing user."""
        email = profile_data.get("username") or profile_data.get("email")
        if not email:
            raise ValueError("email or username is required")

        user = await self._get_user_with_financial_data(email)
        if not user:
            raise ValueError(f"User with email {email} not found")

        # Update scalar financial fields
        if profile_data.get("income") is not None:
            user.income = profile_data["income"]
        if profile_data.get("monthly_income") is not None:
            user.monthly_income = profile_data["monthly_income"]
        if profile_data.get("expenses") is not None:
            user.expenses = profile_data["expenses"]
        if profile_data.get("risk_tolerance") is not None:
            user.risk_tolerance = profile_data["risk_tolerance"]
        if profile_data.get("financial_stage") is not None:
            user.financial_stage = profile_data["financial_stage"]

        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

        # Add related items
        await self._add_related_items(user.id, profile_data)

        # Refresh to get all relationships
        await self._session.refresh(user)
        return user.to_financial_dict()

    async def _add_related_items(self, user_id: int, profile_data: dict) -> None:
        """Add goals, assets, liabilities, insurance, and superannuation to a user."""
        # Add goals
        for goal_data in profile_data.get("goals", []):
            goal = Goal(
                user_id=user_id,
                description=goal_data.get("description", ""),
                amount=goal_data.get("amount"),
                timeline_years=goal_data.get("timeline_years"),
                priority=goal_data.get("priority"),
                motivation=goal_data.get("motivation"),
            )
            self._session.add(goal)

        # Add assets (including cash/savings)
        for asset_data in profile_data.get("assets", []):
            asset = Asset(
                user_id=user_id,
                asset_type=asset_data.get("asset_type", "other"),
                description=asset_data.get("description", ""),
                value=asset_data.get("value"),
                institution=asset_data.get("institution"),
            )
            self._session.add(asset)

        # Add liabilities
        for liability_data in profile_data.get("liabilities", []):
            liability = Liability(
                user_id=user_id,
                liability_type=liability_data.get("liability_type", "other"),
                description=liability_data.get("description", ""),
                amount=liability_data.get("amount"),
                monthly_payment=liability_data.get("monthly_payment"),
                interest_rate=liability_data.get("interest_rate"),
                institution=liability_data.get("institution"),
            )
            self._session.add(liability)

        # Add insurance
        for insurance_data in profile_data.get("insurance", []):
            ins = Insurance(
                user_id=user_id,
                insurance_type=insurance_data.get("insurance_type", "other"),
                provider=insurance_data.get("provider"),
                coverage_amount=insurance_data.get("coverage_amount"),
                monthly_premium=insurance_data.get("monthly_premium"),
            )
            self._session.add(ins)

        # Add superannuation
        for super_data in profile_data.get("superannuation", []):
            superannuation = Superannuation(
                user_id=user_id,
                fund_name=super_data.get("fund_name", "Unknown Fund"),
                account_number=super_data.get("account_number"),
                balance=super_data.get("balance"),
                employer_contribution_rate=super_data.get("employer_contribution_rate"),
                personal_contribution_rate=super_data.get("personal_contribution_rate"),
                investment_option=super_data.get("investment_option"),
                insurance_death=super_data.get("insurance_death"),
                insurance_tpd=super_data.get("insurance_tpd"),
                insurance_income=super_data.get("insurance_income"),
                notes=super_data.get("notes"),
            )
            self._session.add(superannuation)

        await self._session.flush()

    async def add_items(self, email: str, new_items: dict) -> dict:
        """
        Add new goals/assets/liabilities/insurance/superannuation to existing user.
        
        This method ADDS items incrementally without deleting existing ones.
        Scalar fields (income, expenses, etc.) are updated if provided.
        """
        user = await self._get_user_with_financial_data(email)
        
        if not user:
            raise ValueError(f"User with email {email} not found")
        
        # Update scalar fields if provided
        if new_items.get("income") is not None:
            user.income = new_items["income"]
        if new_items.get("monthly_income") is not None:
            user.monthly_income = new_items["monthly_income"]
        if new_items.get("expenses") is not None:
            user.expenses = new_items["expenses"]
        if new_items.get("risk_tolerance") is not None:
            user.risk_tolerance = new_items["risk_tolerance"]
        if new_items.get("financial_stage") is not None:
            user.financial_stage = new_items["financial_stage"]
        
        user.updated_at = datetime.now(timezone.utc)
        
        # ADD new items (don't delete existing ones)
        await self._add_related_items(user.id, new_items)
        
        await self._session.flush()
        await self._session.refresh(user)
        
        return user.to_financial_dict()

    async def update(self, email: str, profile_data: dict) -> dict:
        """Update financial profile for a user (REPLACES related items)."""
        user = await self._get_user_with_financial_data(email)

        if not user:
            raise ValueError(f"User with email {email} not found")

        # Update scalar fields
        if "income" in profile_data:
            user.income = profile_data["income"]
        if "monthly_income" in profile_data:
            user.monthly_income = profile_data["monthly_income"]
        if "expenses" in profile_data:
            user.expenses = profile_data["expenses"]
        if "risk_tolerance" in profile_data:
            user.risk_tolerance = profile_data["risk_tolerance"]
        if "financial_stage" in profile_data:
            user.financial_stage = profile_data["financial_stage"]

        user.updated_at = datetime.now(timezone.utc)

        # Delete and replace related items if provided
        if "goals" in profile_data:
            await self._session.execute(
                delete(Goal).where(Goal.user_id == user.id)
            )
            await self._session.flush()

        if "assets" in profile_data:
            await self._session.execute(
                delete(Asset).where(Asset.user_id == user.id)
            )
            await self._session.flush()

        if "liabilities" in profile_data:
            await self._session.execute(
                delete(Liability).where(Liability.user_id == user.id)
            )
            await self._session.flush()

        if "insurance" in profile_data:
            await self._session.execute(
                delete(Insurance).where(Insurance.user_id == user.id)
            )
            await self._session.flush()

        if "superannuation" in profile_data:
            await self._session.execute(
                delete(Superannuation).where(Superannuation.user_id == user.id)
            )
            await self._session.flush()

        # Add new related items
        await self._add_related_items(user.id, profile_data)

        await self._session.flush()
        await self._session.refresh(user)

        return user.to_financial_dict()

    async def delete(self, email: str) -> None:
        """Delete all financial data for a user (keeps user account)."""
        user = await self._get_user_with_financial_data(email)
        if user:
            # Delete all related financial items
            await self._session.execute(delete(Goal).where(Goal.user_id == user.id))
            await self._session.execute(delete(Asset).where(Asset.user_id == user.id))
            await self._session.execute(delete(Liability).where(Liability.user_id == user.id))
            await self._session.execute(delete(Insurance).where(Insurance.user_id == user.id))
            await self._session.execute(delete(Superannuation).where(Superannuation.user_id == user.id))
            
            # Reset scalar financial fields
            user.income = None
            user.monthly_income = None
            user.expenses = None
            user.risk_tolerance = None
            user.financial_stage = None
            user.updated_at = datetime.now(timezone.utc)
            
            await self._session.flush()

    # Legacy method for backward compatibility
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Legacy method - username is now email."""
        return await self.get_by_email(username)
