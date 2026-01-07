"""Profile management tools for agents."""
import logging
from typing import Dict, Any, Optional, List
from app.core.database import db_manager
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.models.financial import Asset, Liability, Insurance, Superannuation
from sqlalchemy import select

logger = logging.getLogger(__name__)


class ProfileToolkit:
    """Tools for managing financial profile data."""
    
    def __init__(self, user_id: int, username: str):
        """
        Initialize profile toolkit.
        
        Args:
            user_id: User ID for all operations
            username: User email/username
        """
        self.user_id = user_id
        self.username = username
    
    async def get_profile(self) -> Dict[str, Any]:
        """
        Get the user's complete financial profile.
        
        Returns:
            Dictionary with profile data
        """
        async for session in db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(self.username)
            return profile or {}
    
    async def save_financial_fact(
        self,
        fact_type: str,
        value: Any,
        description: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Save a financial fact to the profile.
        
        Args:
            fact_type: Type of fact (income, expenses, asset, liability, etc.)
            value: Value to save
            description: Optional description
            **kwargs: Additional fields specific to fact_type
            
        Returns:
            Updated profile dictionary
        """
        async for session in db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(self.username) or {}
            
            # Update profile based on fact_type
            if fact_type == "income":
                profile["income"] = value
            elif fact_type == "monthly_income":
                profile["monthly_income"] = value
            elif fact_type == "expenses":
                profile["expenses"] = value
            elif fact_type == "risk_tolerance":
                profile["risk_tolerance"] = value
            elif fact_type == "financial_stage":
                profile["financial_stage"] = value
            elif fact_type == "asset":
                # Add asset
                if "assets" not in profile:
                    profile["assets"] = []
                profile["assets"].append({
                    "asset_type": kwargs.get("asset_type", "other"),
                    "description": description or kwargs.get("description", ""),
                    "value": value,
                    "institution": kwargs.get("institution"),
                })
            elif fact_type == "liability":
                # Add liability
                if "liabilities" not in profile:
                    profile["liabilities"] = []
                profile["liabilities"].append({
                    "liability_type": kwargs.get("liability_type", "other"),
                    "description": description or kwargs.get("description", ""),
                    "amount": value,
                    "monthly_payment": kwargs.get("monthly_payment"),
                    "interest_rate": kwargs.get("interest_rate"),
                    "institution": kwargs.get("institution"),
                })
            elif fact_type == "insurance":
                # Add insurance
                if "insurance" not in profile:
                    profile["insurance"] = []
                profile["insurance"].append({
                    "insurance_type": kwargs.get("insurance_type", "other"),
                    "provider": kwargs.get("provider"),
                    "coverage_amount": value,
                    "monthly_premium": kwargs.get("monthly_premium"),
                })
            elif fact_type == "superannuation":
                # Add superannuation
                if "superannuation" not in profile:
                    profile["superannuation"] = []
                profile["superannuation"].append({
                    "fund_name": kwargs.get("fund_name", "Unknown Fund"),
                    "account_number": kwargs.get("account_number"),
                    "balance": value,
                    "employer_contribution_rate": kwargs.get("employer_contribution_rate"),
                    "personal_contribution_rate": kwargs.get("personal_contribution_rate"),
                })
            
            # Save updated profile
            profile["username"] = self.username
            updated = await profile_repo.save(profile)
            
            logger.info(f"Saved financial fact: {fact_type} = {value}")
            return updated
    
    async def get_profile_gaps(self, goals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Identify gaps in the financial profile needed for goal analysis.
        
        Args:
            goals: List of goals to analyze
            
        Returns:
            Dictionary with:
            - gaps: List of missing facts
            - completeness_percentage: 0-100
            - critical_gaps: List of critical missing facts
        """
        profile = await self.get_profile()
        gaps = []
        critical_gaps = []
        score = 0
        max_score = 0
        
        # Check foundational facts
        foundational_facts = {
            "income": ("Income", 20),
            "expenses": ("Monthly expenses", 20),
            "assets": ("Assets", 15),
            "liabilities": ("Liabilities", 15),
        }
        
        for key, (label, points) in foundational_facts.items():
            max_score += points
            if not profile.get(key):
                gaps.append(f"Missing {label.lower()}")
                critical_gaps.append(f"Missing {label.lower()}")
            else:
                score += points
        
        # Check age (needed for retirement calculations)
        if not profile.get("age"):
            gaps.append("Missing age")
            critical_gaps.append("Missing age")
        else:
            score += 10
            max_score += 10
        
        # Check superannuation (for retirement goals)
        has_retirement_goal = any("retire" in g.get("description", "").lower() for g in goals)
        if has_retirement_goal and not profile.get("superannuation"):
            gaps.append("Missing superannuation information")
            critical_gaps.append("Missing superannuation information")
        else:
            if profile.get("superannuation"):
                score += 10
            max_score += 10
        
        # Check risk tolerance
        if not profile.get("risk_tolerance"):
            gaps.append("Missing risk tolerance")
        else:
            score += 10
            max_score += 10
        
        completeness = int((score / max_score * 100)) if max_score > 0 else 0
        
        return {
            "gaps": gaps,
            "critical_gaps": critical_gaps,
            "completeness_percentage": completeness,
            "ready_for_analysis": completeness >= 75,
        }
    
    async def get_profile_summary(self) -> str:
        """
        Get a text summary of the profile for agent context.
        
        Returns:
            Formatted string summary
        """
        profile = await self.get_profile()
        
        summary_parts = []
        
        if profile.get("age"):
            summary_parts.append(f"Age: {profile['age']}")
        if profile.get("income"):
            summary_parts.append(f"Income: ${profile['income']:,.0f}/year")
        if profile.get("monthly_income"):
            summary_parts.append(f"Monthly income: ${profile['monthly_income']:,.0f}")
        if profile.get("expenses"):
            summary_parts.append(f"Monthly expenses: ${profile['expenses']:,.0f}")
        
        if profile.get("assets"):
            total_assets = sum(a.get("value", 0) for a in profile["assets"])
            summary_parts.append(f"Total assets: ${total_assets:,.0f}")
        
        if profile.get("liabilities"):
            total_liabilities = sum(l.get("amount", 0) for l in profile["liabilities"])
            summary_parts.append(f"Total liabilities: ${total_liabilities:,.0f}")
        
        if profile.get("superannuation"):
            total_super = sum(s.get("balance", 0) for s in profile["superannuation"])
            summary_parts.append(f"Superannuation balance: ${total_super:,.0f}")
        
        if profile.get("risk_tolerance"):
            summary_parts.append(f"Risk tolerance: {profile['risk_tolerance']}")
        
        return "\n".join(summary_parts) if summary_parts else "No profile data available"


