"""Financial profile repository implementation using PostgreSQL."""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.interfaces.financial_profile import IFinancialProfileRepository
from app.models.financial_profile import (
    FinancialProfile,
    Goal,
    Asset,
    Liability,
    Insurance,
)


class FinancialProfileRepository(IFinancialProfileRepository):
    """PostgreSQL implementation of financial profile repository using SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a financial profile by username."""
        stmt = (
            select(FinancialProfile)
            .options(
                selectinload(FinancialProfile.goals),
                selectinload(FinancialProfile.assets),
                selectinload(FinancialProfile.liabilities),
                selectinload(FinancialProfile.insurance),
            )
            .where(FinancialProfile.username == username)
        )
        result = await self._session.execute(stmt)
        profile = result.scalar_one_or_none()
        return profile.to_dict() if profile else None

    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data and return the saved profile."""
        username = profile_data["username"]

        # Check if profile already exists
        existing = await self._get_profile_model(username)
        if existing:
            return await self.update(username, profile_data)

        # Create new profile
        profile = FinancialProfile(
            username=username,
            income=profile_data.get("income"),
            monthly_income=profile_data.get("monthly_income"),
            expenses=profile_data.get("expenses"),
            risk_tolerance=profile_data.get("risk_tolerance"),
            financial_stage=profile_data.get("financial_stage"),
        )

        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)

        # Add related items
        await self._add_related_items(profile.id, profile_data)

        # Refresh to get all relationships
        await self._session.refresh(profile)
        return profile.to_dict()

    async def _get_profile_model(self, username: str) -> Optional[FinancialProfile]:
        """Get profile model by username."""
        stmt = (
            select(FinancialProfile)
            .options(
                selectinload(FinancialProfile.goals),
                selectinload(FinancialProfile.assets),
                selectinload(FinancialProfile.liabilities),
                selectinload(FinancialProfile.insurance),
            )
            .where(FinancialProfile.username == username)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _add_related_items(self, profile_id: int, profile_data: dict) -> None:
        """Add goals, assets, liabilities, and insurance to a profile."""
        # Add goals
        for goal_data in profile_data.get("goals", []):
            goal = Goal(
                profile_id=profile_id,
                description=goal_data.get("description", ""),
                amount=goal_data.get("amount"),
                timeline_years=goal_data.get("timeline_years"),
                priority=goal_data.get("priority"),
                motivation=goal_data.get("motivation"),
            )
            self._session.add(goal)

        # Add assets
        for asset_data in profile_data.get("assets", []):
            asset = Asset(
                profile_id=profile_id,
                asset_type=asset_data.get("asset_type", "other"),
                description=asset_data.get("description", ""),
                value=asset_data.get("value"),
                institution=asset_data.get("institution"),
            )
            self._session.add(asset)

        # Add liabilities
        for liability_data in profile_data.get("liabilities", []):
            liability = Liability(
                profile_id=profile_id,
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
                profile_id=profile_id,
                insurance_type=insurance_data.get("insurance_type", "other"),
                provider=insurance_data.get("provider"),
                coverage_amount=insurance_data.get("coverage_amount"),
                monthly_premium=insurance_data.get("monthly_premium"),
            )
            self._session.add(ins)

        await self._session.flush()

    async def update(self, username: str, profile_data: dict) -> dict:
        """Update financial profile for a user."""
        profile = await self._get_profile_model(username)

        if not profile:
            # If profile doesn't exist, create it
            profile_data["username"] = username
            return await self.save(profile_data)

        # Update scalar fields
        if "income" in profile_data:
            profile.income = profile_data["income"]
        if "monthly_income" in profile_data:
            profile.monthly_income = profile_data["monthly_income"]
        if "expenses" in profile_data:
            profile.expenses = profile_data["expenses"]
        if "risk_tolerance" in profile_data:
            profile.risk_tolerance = profile_data["risk_tolerance"]
        if "financial_stage" in profile_data:
            profile.financial_stage = profile_data["financial_stage"]

        profile.updated_at = datetime.now(timezone.utc)

        # Update related items if provided (replace strategy)
        if "goals" in profile_data:
            await self._session.execute(
                delete(Goal).where(Goal.profile_id == profile.id)
            )
            await self._session.flush()

        if "assets" in profile_data:
            await self._session.execute(
                delete(Asset).where(Asset.profile_id == profile.id)
            )
            await self._session.flush()

        if "liabilities" in profile_data:
            await self._session.execute(
                delete(Liability).where(Liability.profile_id == profile.id)
            )
            await self._session.flush()

        if "insurance" in profile_data:
            await self._session.execute(
                delete(Insurance).where(Insurance.profile_id == profile.id)
            )
            await self._session.flush()

        # Add new related items
        await self._add_related_items(profile.id, profile_data)

        await self._session.flush()
        await self._session.refresh(profile)

        return profile.to_dict()

    async def delete(self, username: str) -> None:
        """Delete financial profile for a user."""
        profile = await self._get_profile_model(username)
        if profile:
            await self._session.delete(profile)
            await self._session.flush()
