import re
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from app.schemas.financial import FinancialProfile, Goal, Asset, Liability, Insurance
from app.interfaces.financial_profile import IFinancialProfileRepository


class ProfileExtractor:
    """Service for extracting financial profile information from conversation text.
    
    Analyzes agent responses in real-time to extract financial facts.
    This is a background process that doesn't interrupt conversation flow.
    """
    
    def __init__(self, profile_repository: IFinancialProfileRepository):
        self.profile_repository = profile_repository
    
    def _extract_amounts(self, text: str) -> list[float]:
        """Extract monetary amounts from text."""
        # Pattern for Australian currency: $X, $X.XX, X dollars, etc.
        patterns = [
            r'\$[\d,]+(?:\.\d{2})?',  # $1000, $1,000.50
            r'[\d,]+(?:\.\d{2})?\s*(?:dollars?|AUD)',  # 1000 dollars, 1,000.50 AUD
        ]
        
        amounts = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Clean and convert to float
                cleaned = match.replace('$', '').replace(',', '').replace('dollars', '').replace('AUD', '').strip()
                try:
                    amounts.append(float(cleaned))
                except ValueError:
                    continue
        
        return amounts
    
    def _extract_goals(self, text: str, existing_goals: list) -> list[Goal]:
        """Extract financial goals from text."""
        new_goals = []
        
        # Look for goal-related keywords
        goal_keywords = ['goal', 'want to', 'plan to', 'save for', 'retire', 'buy', 'achieve']
        has_goal_indicators = any(keyword in text.lower() for keyword in goal_keywords)
        
        if has_goal_indicators:
            # Extract amounts mentioned
            amounts = self._extract_amounts(text)
            
            # Try to extract timeline (years)
            timeline_match = re.search(r'(\d+)\s*(?:years?|yrs?)', text, re.IGNORECASE)
            timeline = float(timeline_match.group(1)) if timeline_match else None
            
            # Extract description (simplified - in production, use LLM for better extraction)
            # For now, use sentences containing goal keywords
            sentences = re.split(r'[.!?]+', text)
            for sentence in sentences:
                if any(keyword in sentence.lower() for keyword in goal_keywords):
                    description = sentence.strip()
                    if description and len(description) > 10:
                        goal = Goal(
                            description=description,
                            amount=amounts[0] if amounts else None,
                            timeline_years=timeline,
                            created_at=datetime.now(timezone.utc)
                        )
                        # Check if similar goal already exists
                        if not any(g.description == goal.description for g in existing_goals):
                            new_goals.append(goal)
        
        return new_goals
    
    def _extract_assets(self, text: str, existing_assets: list) -> list[Asset]:
        """Extract assets from text."""
        new_assets = []
        
        asset_keywords = {
            'superannuation': ['super', 'superannuation', 'super fund'],
            'savings': ['savings', 'saved', 'bank account', 'deposit'],
            'investment': ['investment', 'invested', 'shares', 'stocks', 'portfolio'],
            'property': ['property', 'house', 'home', 'real estate']
        }
        
        amounts = self._extract_amounts(text)
        
        for asset_type, keywords in asset_keywords.items():
            if any(keyword in text.lower() for keyword in keywords):
                # Extract description
                sentences = re.split(r'[.!?]+', text)
                for sentence in sentences:
                    if any(keyword in sentence.lower() for keyword in keywords):
                        description = sentence.strip()
                        if description and len(description) > 10:
                            asset = Asset(
                                asset_type=asset_type,
                                description=description,
                                value=amounts[0] if amounts else None,
                                created_at=datetime.now(timezone.utc)
                            )
                            # Check if similar asset already exists
                            if not any(a.description == asset.description for a in existing_assets):
                                new_assets.append(asset)
        
        return new_assets
    
    def _extract_liabilities(self, text: str, existing_liabilities: list) -> list[Liability]:
        """Extract liabilities from text."""
        new_liabilities = []
        
        liability_keywords = {
            'mortgage': ['mortgage', 'home loan', 'house loan'],
            'loan': ['loan', 'personal loan', 'car loan'],
            'credit_card': ['credit card', 'credit card debt']
        }
        
        amounts = self._extract_amounts(text)
        
        for liability_type, keywords in liability_keywords.items():
            if any(keyword in text.lower() for keyword in keywords):
                sentences = re.split(r'[.!?]+', text)
                for sentence in sentences:
                    if any(keyword in sentence.lower() for keyword in keywords):
                        description = sentence.strip()
                        if description and len(description) > 10:
                            liability = Liability(
                                liability_type=liability_type,
                                description=description,
                                amount=amounts[0] if amounts else None,
                                created_at=datetime.now(timezone.utc)
                            )
                            if not any(l.description == liability.description for l in existing_liabilities):
                                new_liabilities.append(liability)
        
        return new_liabilities
    
    def _extract_income_expenses(self, text: str) -> tuple[Optional[float], Optional[float]]:
        """Extract income and expenses from text."""
        income = None
        expenses = None
        
        # Look for income indicators
        income_keywords = ['income', 'earn', 'salary', 'wage', 'annual income', 'monthly income']
        if any(keyword in text.lower() for keyword in income_keywords):
            amounts = self._extract_amounts(text)
            if amounts:
                # Check if it's annual or monthly
                if 'annual' in text.lower() or 'yearly' in text.lower():
                    income = amounts[0]
                elif 'monthly' in text.lower():
                    income = amounts[0] * 12  # Convert to annual
                else:
                    income = amounts[0]  # Assume annual
        
        # Look for expense indicators
        expense_keywords = ['expense', 'spend', 'monthly expense', 'cost']
        if any(keyword in text.lower() for keyword in expense_keywords):
            amounts = self._extract_amounts(text)
            if amounts:
                expenses = amounts[0]
        
        return income, expenses
    
    def _extract_risk_tolerance(self, text: str) -> Optional[str]:
        """Extract risk tolerance from text."""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['low risk', 'conservative', 'safe']):
            return 'Low'
        elif any(word in text_lower for word in ['high risk', 'aggressive', 'risky']):
            return 'High'
        elif any(word in text_lower for word in ['medium risk', 'moderate', 'balanced']):
            return 'Medium'
        
        return None
    
    async def extract_and_update_profile(
        self,
        username: str,
        conversation_text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract financial facts from conversation text and update profile.
        
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
                "insurance": []
            }
            existing_profile = await self.profile_repository.save(profile_data)
        
        changes = {}
        updated = False
        
        # Extract goals
        existing_goals = [Goal(**g) if isinstance(g, dict) else g for g in existing_profile.get("goals", [])]
        new_goals = self._extract_goals(conversation_text, existing_goals)
        if new_goals:
            existing_profile["goals"].extend([g.model_dump() for g in new_goals])
            changes["goals"] = [g.model_dump() for g in new_goals]
            updated = True
        
        # Extract assets
        existing_assets = [Asset(**a) if isinstance(a, dict) else a for a in existing_profile.get("assets", [])]
        new_assets = self._extract_assets(conversation_text, existing_assets)
        if new_assets:
            existing_profile["assets"].extend([a.model_dump() for a in new_assets])
            changes["assets"] = [a.model_dump() for a in new_assets]
            updated = True
        
        # Extract liabilities
        existing_liabilities = [Liability(**l) if isinstance(l, dict) else l for l in existing_profile.get("liabilities", [])]
        new_liabilities = self._extract_liabilities(conversation_text, existing_liabilities)
        if new_liabilities:
            existing_profile["liabilities"].extend([l.model_dump() for l in new_liabilities])
            changes["liabilities"] = [l.model_dump() for l in new_liabilities]
            updated = True
        
        # Extract income/expenses
        income, expenses = self._extract_income_expenses(conversation_text)
        if income and (not existing_profile.get("income") or income != existing_profile.get("income")):
            existing_profile["income"] = income
            changes["income"] = income
            updated = True
        
        if expenses and (not existing_profile.get("expenses") or expenses != existing_profile.get("expenses")):
            existing_profile["expenses"] = expenses
            changes["expenses"] = expenses
            updated = True
        
        # Extract risk tolerance
        risk_tolerance = self._extract_risk_tolerance(conversation_text)
        if risk_tolerance and (not existing_profile.get("risk_tolerance") or risk_tolerance != existing_profile.get("risk_tolerance")):
            existing_profile["risk_tolerance"] = risk_tolerance
            changes["risk_tolerance"] = risk_tolerance
            updated = True
        
        if updated:
            # Update profile in repository
            updated_profile = await self.profile_repository.update(username, existing_profile)
            return {
                "changes": changes,
                "profile": updated_profile
            }
        
        return None

