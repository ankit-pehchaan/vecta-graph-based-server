"""Workflow Service for managing user workflow instances and WebSocket integration."""
import logging
import re
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
from fastapi import WebSocket
from app.workflows.financial_advisor_workflow import FinancialAdvisorWorkflow
from app.core.database import DatabaseManager
from app.core.agent_storage import get_agent_storage
from app.services.visualization_service import VisualizationService
from app.services.viz_intent_agent_service import LoanVizInputs, CardSpec
from app.schemas.advice import VisualizationMessage, VizSeries, VizPoint
from app.services.finance_calculators import FREQUENCY_PER_YEAR

logger = logging.getLogger(__name__)


class WorkflowService:
    """
    Service to manage Financial Advisor Workflow instances per user.
    
    Handles:
    - Creating and caching workflow instances
    - Streaming workflow responses to WebSocket
    - Managing workflow session state
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize workflow service.
        
        Args:
            db_manager: Database manager instance
        """
        self.db_manager = db_manager
        self.workflows: Dict[int, FinancialAdvisorWorkflow] = {}
        self.visualization_service = VisualizationService()
        logger.info("WorkflowService initialized")
    
    def get_workflow(self, user_id: int) -> FinancialAdvisorWorkflow:
        """
        Get or create workflow instance for user.
        
        Implements caching to avoid recreating workflows (per Agno best practices).
        
        Args:
            user_id: User ID
            
        Returns:
            FinancialAdvisorWorkflow instance
        """
        if user_id not in self.workflows:
            logger.info(f"Creating new workflow for user {user_id}")
            self.workflows[user_id] = FinancialAdvisorWorkflow(
                db=get_agent_storage(),
                session_id=f"user_{user_id}",
                db_manager=self.db_manager,
            )
        else:
            logger.debug(f"Returning cached workflow for user {user_id}")
        
        return self.workflows[user_id]
    
    def _get_profile_data(self, workflow: FinancialAdvisorWorkflow, user_id: int) -> Dict[str, Any]:
        """
        Get profile data from workflow session state.
        
        Args:
            workflow: Workflow instance
            user_id: User ID
            
        Returns:
            Dictionary with profile data
        """
        discovered_facts = workflow.session_state.get("discovered_facts", {})
        discovered_goals = workflow.session_state.get("discovered_goals", [])
        goals_with_timelines = workflow.session_state.get("goals_with_timelines", [])
        
        # Build assets array
        assets = []
        if discovered_facts.get("savings"):
            assets.append({"asset_type": "cash", "value": discovered_facts.get("savings", 0)})
        if discovered_facts.get("property_value"):
            assets.append({"asset_type": "property", "value": discovered_facts.get("property_value", 0)})
        if discovered_facts.get("investments_value"):
            assets.append({"asset_type": "investment", "value": discovered_facts.get("investments_value", 0)})
        
        # Build liabilities array
        liabilities = []
        if discovered_facts.get("home_loan_amount"):
            liabilities.append({
                "liability_type": "mortgage",
                "amount": discovered_facts.get("home_loan_amount", 0),
                "interest_rate": discovered_facts.get("home_loan_interest_rate"),
            })
        if discovered_facts.get("car_loan_amount"):
            liabilities.append({
                "liability_type": "car_loan",
                "amount": discovered_facts.get("car_loan_amount", 0),
                "interest_rate": discovered_facts.get("car_loan_interest_rate"),
            })
        if discovered_facts.get("personal_loans_amount"):
            liabilities.append({
                "liability_type": "personal_loan",
                "amount": discovered_facts.get("personal_loans_amount", 0),
            })
        if discovered_facts.get("credit_card_debt"):
            liabilities.append({
                "liability_type": "credit_card",
                "amount": discovered_facts.get("credit_card_debt", 0),
            })
        
        # Build superannuation array
        superannuation = []
        if discovered_facts.get("superannuation_balance"):
            superannuation.append({
                "balance": discovered_facts.get("superannuation_balance", 0),
            })
        
        return {
            "assets": assets,
            "liabilities": liabilities,
            "superannuation": superannuation,
            "income": discovered_facts.get("income"),
            "monthly_income": discovered_facts.get("monthly_income"),
            "expenses": discovered_facts.get("monthly_living_expenses") or discovered_facts.get("expenses"),
            "goals": discovered_goals,
            "goals_with_timelines": goals_with_timelines,
            "discovered_facts": discovered_facts,
        }
    
    def _check_data_requirements(
        self, 
        query_type: str, 
        profile_data: Dict[str, Any]
    ) -> Tuple[List[str], Dict[str, List[str]]]:
        """
        Check what data is required and what's missing for the query type.
        
        Args:
            query_type: Type of query ('loan', 'forecast', 'assets_vs_liabilities', etc.)
            profile_data: Available profile data
            
        Returns:
            Tuple of (missing_data_list, needed_fields_dict)
        """
        missing_data = []
        needed_fields = {}
        
        if query_type == "loan":
            needed_fields["required"] = ["principal", "term_years", "interest_rate"]
            # Check if we can extract from message or need to ask
            # This will be handled in _extract_loan_parameters
        
        elif query_type in ["assets_vs_liabilities", "balance_sheet", "net_worth"]:
            needed_fields["required"] = ["assets", "liabilities"]
            assets = profile_data.get("assets", [])
            liabilities = profile_data.get("liabilities", [])
            
            if not assets or sum(a.get("value", 0) for a in assets) == 0:
                missing_data.append("assets")
            if not liabilities or sum(l.get("amount", 0) for l in liabilities) == 0:
                missing_data.append("liabilities")
        
        elif query_type == "forecast" or query_type == "savings_projection":
            needed_fields["required"] = ["income", "expenses", "savings"]
            if not profile_data.get("income") and not profile_data.get("monthly_income"):
                missing_data.append("income")
            if not profile_data.get("expenses"):
                missing_data.append("expenses")
            if not profile_data.get("assets") or not any(a.get("asset_type") == "cash" for a in profile_data.get("assets", [])):
                missing_data.append("savings")
        
        elif query_type == "general":
            # For general queries, check if we have any financial data
            has_assets = bool(profile_data.get("assets"))
            has_liabilities = bool(profile_data.get("liabilities"))
            has_income = bool(profile_data.get("income") or profile_data.get("monthly_income"))
            
            if not (has_assets or has_liabilities or has_income):
                missing_data.append("financial_data")
        
        return (missing_data, needed_fields)
    
    def _generate_data_request_question(
        self, 
        query_type: str, 
        missing_data: List[str], 
        needed_fields: Dict[str, List[str]]
    ) -> str:
        """
        Generate a question to ask for missing data.
        
        Args:
            query_type: Type of query
            missing_data: List of missing data fields
            needed_fields: Dictionary of needed fields
            
        Returns:
            Question string to ask user
        """
        if "assets" in missing_data and "liabilities" in missing_data:
            return "I'd love to show you your financial position! To create this visualization, I need to know about your assets (savings, property, investments) and liabilities (loans, debts). Could you tell me about these?"
        elif "assets" in missing_data:
            return "To show your assets vs liabilities, I need to know about your assets. What assets do you have? (savings, property, investments, etc.)"
        elif "liabilities" in missing_data:
            return "To show your assets vs liabilities, I need to know about your debts and loans. What liabilities do you have?"
        elif "income" in missing_data:
            return "To create a forecast, I need to know your income. What's your annual or monthly income?"
        elif "expenses" in missing_data:
            return "To create a forecast, I need to know your monthly expenses. What are your typical monthly expenses?"
        elif "savings" in missing_data:
            return "To create a savings projection, I need to know your current savings. How much do you have in savings?"
        elif "financial_data" in missing_data:
            return "To create this visualization, I need some financial information. Could you tell me about your income, assets, or debts?"
        else:
            return "I need a bit more information to create this visualization. Could you provide the missing details?"
    
    async def _generate_immediate_viz(
        self,
        query_type: str,
        message: str,
        profile_data: Dict[str, Any],
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Generate immediate visualization based on query type and available data.
        
        Args:
            query_type: Type of query
            message: User's message
            profile_data: Available profile data
            user_id: User ID
            
        Returns:
            Visualization dict or None
        """
        try:
            if query_type == "loan":
                # Use existing loan visualization logic
                params = self._extract_loan_parameters(message, user_id)
                if params:
                    return self._generate_immediate_loan_viz(params)
            
            elif query_type in ["assets_vs_liabilities", "balance_sheet"]:
                return self._generate_assets_vs_liabilities_viz(profile_data)
            
            elif query_type in ["forecast", "savings_projection"]:
                return self._generate_forecast_viz(profile_data, message)
            
            elif query_type == "net_worth":
                return self._generate_net_worth_viz(profile_data)
            
            elif query_type == "general":
                # Try to generate a general financial snapshot
                return self._generate_general_snapshot_viz(profile_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error generating immediate visualization for {query_type}: {e}", exc_info=True)
            return None
    
    def _generate_assets_vs_liabilities_viz(self, profile_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate assets vs liabilities visualization."""
        from app.schemas.advice import VisualizationMessage, VizChart, VizSeries, VizPoint
        import uuid
        
        assets = profile_data.get("assets", [])
        liabilities = profile_data.get("liabilities", [])
        superannuation = profile_data.get("superannuation", [])
        
        total_assets = sum(a.get("value", 0) for a in assets)
        total_liabilities = sum(l.get("amount", 0) for l in liabilities)
        total_super = sum(s.get("balance", 0) for s in superannuation)
        net_worth = total_assets + total_super - total_liabilities
        
        # Create data points
        data_points = []
        if total_assets > 0:
            data_points.append(VizPoint(x="Assets", y=float(total_assets)))
        if total_super > 0:
            data_points.append(VizPoint(x="Superannuation", y=float(total_super)))
        if total_liabilities > 0:
            data_points.append(VizPoint(x="Liabilities", y=float(total_liabilities)))
        
        if not data_points:
            return None
        
        viz_message = VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title="Assets vs Liabilities",
            subtitle=f"Net Worth: ${net_worth:,.0f}",
            narrative=f"Your total assets are ${total_assets:,.0f}, superannuation is ${total_super:,.0f}, and liabilities are ${total_liabilities:,.0f}. Net worth: ${net_worth:,.0f}.",
            chart=VizChart(
                kind="bar",
                x_label="",
                y_label="Amount (AUD)",
                y_unit="AUD",
            ),
            series=[VizSeries(name="Financial Position", data=data_points)],
            assumptions=["Values are based on your current profile data."],
            meta={
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "viz_kind": "assets_vs_liabilities",
            },
        )
        
        if hasattr(viz_message, 'model_dump'):
            return viz_message.model_dump()
        return None
    
    def _generate_forecast_viz(self, profile_data: Dict[str, Any], message: str) -> Optional[Dict[str, Any]]:
        """Generate forecast/savings projection visualization."""
        from app.schemas.advice import VisualizationMessage, VizChart, VizSeries, VizPoint
        from app.services.finance_calculators import FREQUENCY_PER_YEAR
        import uuid
        
        income = profile_data.get("income") or (profile_data.get("monthly_income") or 0) * 12
        expenses = profile_data.get("expenses") or 0
        monthly_savings = (income / 12) - expenses if income else 0
        
        # Get current savings
        assets = profile_data.get("assets", [])
        current_savings = 0
        for asset in assets:
            if asset.get("asset_type") == "cash":
                current_savings = asset.get("value", 0)
                break
        
        # Extract years from message if mentioned
        years = 10  # Default
        years_match = re.search(r'(\d+)\s*(?:years?|yrs?)', message.lower())
        if years_match:
            try:
                years = min(int(years_match.group(1)), 30)  # Cap at 30 years
            except ValueError:
                pass
        
        # Project savings over time
        points = []
        savings = current_savings
        for year in range(0, years + 1):
            points.append(VizPoint(x=year, y=float(savings)))
            savings += monthly_savings * 12
        
        viz_message = VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title="Savings Forecast",
            subtitle=f"Projected over {years} years",
            narrative=f"Based on your current savings of ${current_savings:,.0f} and monthly savings of ${monthly_savings:,.0f}, your savings are projected to reach ${savings:,.0f} in {years} years.",
            chart=VizChart(
                kind="line",
                x_label="Year",
                y_label="Savings (AUD)",
                y_unit="AUD",
            ),
            series=[VizSeries(name="Projected Savings", data=points)],
            assumptions=[
                f"Assumes monthly savings of ${monthly_savings:,.0f} (income - expenses).",
                "No interest or investment returns included.",
            ],
            meta={
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "viz_kind": "savings_forecast",
            },
        )
        
        if hasattr(viz_message, 'model_dump'):
            return viz_message.model_dump()
        return None
    
    def _generate_net_worth_viz(self, profile_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate net worth visualization (same as assets vs liabilities but focused on net worth)."""
        return self._generate_assets_vs_liabilities_viz(profile_data)
    
    def _generate_general_snapshot_viz(self, profile_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate a general financial snapshot visualization."""
        # Use the profile snapshot cards from VisualizationService
        try:
            cards = self.visualization_service.build_profile_snapshot_cards(
                profile_data=profile_data,
                currency="AUD",
                max_cards=1
            )
            if cards and len(cards) > 0:
                if hasattr(cards[0], 'model_dump'):
                    return cards[0].model_dump()
        except Exception as e:
            logger.warning(f"Could not generate general snapshot: {e}")
        
        return None
    
    def clear_workflow(self, user_id: int):
        """
        Clear workflow instance for user (reset conversation).
        
        Args:
            user_id: User ID
        """
        if user_id in self.workflows:
            del self.workflows[user_id]
            logger.info(f"Cleared workflow for user {user_id}")
    
    def _detect_mathematical_query(self, message: str) -> Tuple[bool, Optional[str]]:
        """
        Detect if message is a mathematical/forecasting query that needs visualization.
        
        Args:
            message: User's message
            
        Returns:
            Tuple of (is_mathematical_query, query_type)
            query_type can be: 'loan', 'forecast', 'assets_vs_liabilities', 'net_worth', 
                              'savings_projection', 'balance_sheet', 'general'
        """
        message_lower = message.lower()
        
        # Mathematical/visualization request keywords
        visualization_keywords = [
            "show me", "show", "visualize", "visualization", "chart", "graph", "plot",
            "forecast", "projection", "predict", "what will", "how much will",
            "calculate", "compare", "comparison", "vs", "versus", "breakdown",
            "snapshot", "overview", "summary", "break down", "split"
        ]
        
        # Loan-specific keywords
        loan_keywords = ["loan", "mortgage", "debt", "repayment", "pay off", "payoff", "amortization"]
        
        # Financial position keywords
        position_keywords = [
            "assets", "liabilities", "net worth", "networth", "balance sheet",
            "financial position", "financial snapshot", "where am i", "financial status"
        ]
        
        # Forecast/projection keywords
        forecast_keywords = [
            "forecast", "projection", "future", "in 5 years", "in 10 years",
            "what will", "how much will", "savings", "growth", "trajectory"
        ]
        
        # Check for visualization intent
        has_viz_keyword = any(keyword in message_lower for keyword in visualization_keywords)
        
        # Determine specific query type
        query_type = None
        
        # Loan calculation
        if any(keyword in message_lower for keyword in loan_keywords):
            if has_viz_keyword or any(kw in message_lower for kw in ["years", "term", "instead of", "rather than"]):
                query_type = "loan"
        
        # Assets vs liabilities / net worth
        if any(keyword in message_lower for keyword in position_keywords):
            query_type = "assets_vs_liabilities"
        
        # Forecast/projection
        if any(keyword in message_lower for keyword in forecast_keywords):
            query_type = "forecast"
        
        # Savings projection
        if "savings" in message_lower and any(kw in message_lower for kw in ["projection", "forecast", "future", "growth"]):
            query_type = "savings_projection"
        
        # Balance sheet
        if "balance sheet" in message_lower or ("assets" in message_lower and "liabilities" in message_lower):
            query_type = "balance_sheet"
        
        # General mathematical query (has numbers and visualization keywords)
        if query_type is None and has_viz_keyword:
            # Check for numeric patterns
            has_numbers = bool(re.search(r'\$?\d+[kkm]?[\s,]*\d*', message_lower))
            if has_numbers:
                query_type = "general"
        
        # Return True if we detected a mathematical query
        is_mathematical = query_type is not None
        
        return (is_mathematical, query_type)
    
    def _extract_loan_parameters(
        self, 
        message: str, 
        user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Extract loan parameters from user message.
        
        Args:
            message: User's message
            user_id: Optional user ID to get interest rate from profile
            
        Returns:
            Dictionary with loan parameters or None if extraction fails
        """
        message_lower = message.lower()
        
        # Extract principal amount
        principal = None
        # Patterns: "$50k", "50k", "50 thousand", "$50,000", "50000"
        amount_patterns = [
            r'\$?\s*(\d+(?:[,\s]\d{3})*)\s*(?:k|thousand|grand)',
            r'\$?\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?)',
        ]
        
        for pattern in amount_patterns:
            match = re.search(pattern, message_lower)
            if match:
                amount_str = match.group(1).replace(',', '').replace(' ', '')
                try:
                    principal = float(amount_str)
                    # If it's a small number (< 100) and followed by k/thousand, multiply by 1000
                    if principal < 100 and ('k' in match.group(0) or 'thousand' in match.group(0) or 'grand' in match.group(0)):
                        principal *= 1000
                    break
                except ValueError:
                    continue
        
        if principal is None or principal <= 0:
            return None
        
        # Extract term years (new desired term)
        new_term = None
        # Patterns: "5 years", "in 5 years", "pay off in 5 years", "5 year term"
        term_patterns = [
            r'(?:in|for|within|pay\s+off\s+in)\s+(\d+)\s*(?:years?|yrs?)',
            r'(\d+)\s*(?:years?|yrs?)\s*(?:rather\s+than|instead\s+of|vs|versus)',
            r'(\d+)\s*(?:years?|yrs?)\s*(?:term|period)',
        ]
        
        for pattern in term_patterns:
            match = re.search(pattern, message_lower)
            if match:
                try:
                    new_term = int(match.group(1))
                    if 1 <= new_term <= 50:
                        break
                except ValueError:
                    continue
        
        # Extract original term (if mentioned in comparison)
        original_term = None
        # First try to match the full comparison pattern: "X years rather than Y years"
        comparison_pattern = r'(\d+)\s*(?:years?|yrs?)\s*(?:rather\s+than|instead\s+of|vs|versus)\s+(\d+)\s*(?:years?|yrs?)'
        match = re.search(comparison_pattern, message_lower)
        if match:
            try:
                # In "X years rather than Y years", X is new term, Y is original
                # But we may have already extracted new_term, so check which one matches
                extracted_new = int(match.group(1))
                extracted_original = int(match.group(2))
                
                # If new_term was already set and matches the first number, use second as original
                if new_term and new_term == extracted_new:
                    original_term = extracted_original
                # If new_term wasn't set yet, first number is new_term, second is original
                elif not new_term:
                    new_term = extracted_new
                    original_term = extracted_original
                # If new_term was set but doesn't match, second number might be original
                elif new_term != extracted_new:
                    original_term = extracted_original
            except (ValueError, IndexError):
                pass
        
        # If still no original_term found, try simpler pattern
        if original_term is None:
            simple_comparison = re.search(r'(\d+)\s*(?:years?|yrs?)\s*(?:rather\s+than|instead\s+of)', message_lower)
            if simple_comparison:
                # Look for another year mention in the message
                all_year_matches = re.findall(r'(\d+)\s*(?:years?|yrs?)', message_lower)
                if len(all_year_matches) >= 2:
                    # Find the one that's not the new_term
                    for year_str in all_year_matches:
                        year_val = int(year_str)
                        if year_val != new_term and 1 <= year_val <= 50:
                            original_term = year_val
                            break
        
        # Extract interest rate
        interest_rate = None
        rate_patterns = [
            r'(\d+(?:\.\d+)?)\s*%',
            r'(\d+(?:\.\d+)?)\s*percent',
            r'at\s+(\d+(?:\.\d+)?)\s*%',
            r'interest\s+(?:rate\s+)?(?:of\s+)?(\d+(?:\.\d+)?)',
        ]
        
        for pattern in rate_patterns:
            match = re.search(pattern, message_lower)
            if match:
                try:
                    interest_rate = float(match.group(1))
                    if 0 <= interest_rate <= 30:  # Reasonable range
                        break
                except ValueError:
                    continue
        
        # If no interest rate found, try to get from user profile or use default
        if interest_rate is None:
            if user_id:
                # Try to get from workflow session state
                workflow = self.get_workflow(user_id)
                discovered_facts = workflow.session_state.get("discovered_facts", {})
                # Check for home loan interest rate first
                interest_rate = discovered_facts.get("home_loan_interest_rate")
                if interest_rate is None:
                    interest_rate = discovered_facts.get("car_loan_interest_rate")
            # Default to 5.5% if still not found
            if interest_rate is None:
                interest_rate = 5.5
        
        # Must have at least principal and new_term
        if principal and new_term:
            return {
                "principal": principal,
                "term_years": new_term,
                "original_term_years": original_term,
                "annual_rate_percent": interest_rate,
                "payment_frequency": "monthly",  # Default
                "is_comparison": original_term is not None,
            }
        
        return None
    
    def _generate_immediate_loan_viz(
        self, 
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate loan visualization immediately for simple calculation queries.
        
        Args:
            params: Loan parameters dictionary
            
        Returns:
            VisualizationMessage dict ready for WebSocket or None if generation fails
        """
        try:
            principal = params["principal"]
            term_years = params["term_years"]
            annual_rate_percent = params["annual_rate_percent"]
            payment_frequency = params.get("payment_frequency", "monthly")
            is_comparison = params.get("is_comparison", False)
            original_term = params.get("original_term_years")
            
            # Create LoanVizInputs
            loan_inputs = LoanVizInputs(
                principal=principal,
                annual_rate_percent=annual_rate_percent,
                term_years=term_years,
                payment_frequency=payment_frequency,
                currency="AUD",
            )
            
            # Create a basic CardSpec for the visualization
            card = CardSpec(
                title="Loan Repayment Comparison" if is_comparison else "Loan Repayment Trajectory",
                subtitle=f"${principal:,.0f} at {annual_rate_percent}%",
                calc_kind="loan_amortization",
                loan=loan_inputs,
            )
            
            # Generate baseline visualization
            viz_message = self.visualization_service._build_loan_viz(loan_inputs, card)
            
            # If comparison scenario, add original term as second series
            if is_comparison and original_term:
                from app.services.finance_calculators import amortize_balance_trajectory
                
                # Helper function to downsample balances to yearly points
                def downsample_to_years(balances, payment_freq, term_yrs):
                    freq = FREQUENCY_PER_YEAR[payment_freq]
                    points = []
                    points.append(VizPoint(x=0, y=float(balances[0])))
                    for year in range(1, term_yrs + 1):
                        idx = min(year * freq, len(balances) - 1)
                        points.append(VizPoint(x=year, y=float(balances[idx])))
                        if balances[idx] <= 0:
                            break
                    return points
                
                # Calculate original term trajectory
                original_balances, original_summary = amortize_balance_trajectory(
                    principal=principal,
                    annual_rate_percent=annual_rate_percent,
                    term_years=original_term,
                    payment_frequency=payment_frequency,
                    extra_payment=0.0,
                )
                original_points = downsample_to_years(
                    original_balances, payment_frequency, original_term
                )
                
                # Calculate new term trajectory
                new_balances, new_summary = amortize_balance_trajectory(
                    principal=principal,
                    annual_rate_percent=annual_rate_percent,
                    term_years=term_years,
                    payment_frequency=payment_frequency,
                    extra_payment=0.0,
                )
                new_points = downsample_to_years(
                    new_balances, payment_frequency, term_years
                )
                
                # Update series with both trajectories
                viz_message.series = [
                    VizSeries(name=f"{original_term} years (original)", data=original_points),
                    VizSeries(name=f"{term_years} years (new)", data=new_points),
                ]
                
                # Update narrative with comparison details
                interest_saved = original_summary.total_interest - new_summary.total_interest
                time_saved = original_term - term_years
                
                narrative_parts = [
                    f"Original term ({original_term} years): Total interest ${original_summary.total_interest:,.2f}",
                    f"New term ({term_years} years): Total interest ${new_summary.total_interest:,.2f}",
                ]
                
                if interest_saved > 0:
                    narrative_parts.append(
                        f"You would save ${interest_saved:,.2f} in interest by paying off in {term_years} years instead of {original_term} years."
                    )
                else:
                    narrative_parts.append(
                        f"Paying off in {term_years} years instead of {original_term} years would increase interest by ${abs(interest_saved):,.2f}."
                    )
                
                narrative_parts.append(f"Time saved: {time_saved} years")
                
                viz_message.narrative = " ".join(narrative_parts)
                viz_message.title = f"Loan Comparison: {term_years} years vs {original_term} years"
            
            # Convert to dict for WebSocket
            if hasattr(viz_message, 'model_dump'):
                return viz_message.model_dump()
            elif hasattr(viz_message, 'dict'):
                return viz_message.dict()
            else:
                # Manual conversion if needed
                return {
                    "viz_id": str(viz_message.viz_id) if hasattr(viz_message, 'viz_id') else None,
                    "title": viz_message.title,
                    "subtitle": viz_message.subtitle,
                    "narrative": viz_message.narrative,
                    "chart": {
                        "kind": viz_message.chart.kind if hasattr(viz_message, 'chart') else "line",
                        "x_label": viz_message.chart.x_label if hasattr(viz_message, 'chart') else "Year",
                        "y_label": viz_message.chart.y_label if hasattr(viz_message, 'chart') else "Remaining balance",
                        "y_unit": viz_message.chart.y_unit if hasattr(viz_message, 'chart') else "AUD",
                    } if hasattr(viz_message, 'chart') else None,
                    "series": [
                        {
                            "name": s.name,
                            "data": [{"x": p.x, "y": p.y} if hasattr(p, 'x') else p for p in s.data]
                        } for s in viz_message.series
                    ] if hasattr(viz_message, 'series') else [],
                    "assumptions": viz_message.assumptions if hasattr(viz_message, 'assumptions') else [],
                    "explore_next": viz_message.explore_next if hasattr(viz_message, 'explore_next') else [],
                    "meta": viz_message.meta if hasattr(viz_message, 'meta') else {},
                }
                
        except Exception as e:
            logger.error(f"Error generating immediate loan visualization: {e}", exc_info=True)
            return None
    
    async def handle_message(
        self,
        websocket: WebSocket,
        user_id: int,
        message: str
    ):
        """
        Process user message through workflow and stream response to WebSocket.
        
        Args:
            websocket: WebSocket connection
            user_id: User ID
            message: User's message
        """
        workflow = self.get_workflow(user_id)
        
        try:
            logger.info(f"Processing message for user {user_id}: {message[:50]}...")
            
            # Check for mathematical/forecasting queries FIRST - show visualization immediately
            is_mathematical, query_type = self._detect_mathematical_query(message)
            
            if is_mathematical:
                logger.info(f"Detected mathematical query type: {query_type}")
                
                # Get available profile data
                profile_data = self._get_profile_data(workflow, user_id)
                
                # Check what data is needed and what's missing
                missing_data, needed_fields = self._check_data_requirements(query_type, profile_data)
                
                if missing_data:
                    # Data is missing - ask for it
                    question = self._generate_data_request_question(query_type, missing_data, needed_fields)
                    await websocket.send_json({
                        "type": "agent_response",
                        "content": question,
                        "is_complete": True,
                        "metadata": {
                            "phase": "data_collection",
                            "query_type": query_type,
                            "missing_fields": missing_data,
                        }
                    })
                    logger.info(f"Asked for missing data: {missing_data}")
                else:
                    # Data is available - generate visualization immediately
                    viz_data = await self._generate_immediate_viz(query_type, message, profile_data, user_id)
                    
                    if viz_data:
                        # Send visualization FIRST before any text response
                        await websocket.send_json({
                            "type": "visualization",
                            "data": viz_data,
                            "metadata": {
                                "phase": "immediate_calculation",
                                "query_type": query_type,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        })
                        logger.info(f"✓ Sent immediate visualization: {viz_data.get('title', 'Unknown')} ({query_type})")
                    else:
                        logger.warning(f"Failed to generate immediate visualization for {query_type}, continuing with normal workflow")
            
            # Route based on current phase
            current_phase = workflow.session_state.get("current_phase", "iterative_discovery")
            
            if current_phase == "iterative_discovery":
                # Use Agno's steps pattern for iterative discovery
                result = await workflow._iterative_discovery_steps(workflow.session_state, message)
                
                # Update workflow's session_state with result
                workflow.session_state = result.get("session_state", workflow.session_state)
                
                # Update phase if transitioned
                if result.get("next_phase"):
                    workflow.session_state["current_phase"] = result["next_phase"]
                    current_phase = result["next_phase"]
                
                # Send response to WebSocket (only if there's content)
                content = result.get("response", "")
                if content and content.strip():
                    await websocket.send_json({
                        "type": "agent_response",
                        "content": content,
                        "is_complete": result.get("is_complete", False),
                        "metadata": {
                            "phase": current_phase,
                            "iteration": workflow.session_state.get("iteration_count", 0),
                            "conversation_turn": workflow.session_state.get("conversation_turns", 0)
                        }
                    })
            else:
                # For goal_strategy and deep_dive, use run() method which yields WorkflowResponse
                # Send processing status when generating visualizations
                if current_phase in ["goal_strategy", "deep_dive"]:
                    await websocket.send_json({
                        "type": "processing",
                        "status": True,
                        "message": "Generating visualizations and analysis..."
                    })
                
                # Process workflow.run() which yields WorkflowResponse objects
                for response in workflow.run(message, user_id):
                    # Handle different event types
                    if response.event == "visualization":
                        # Send visualization event
                        viz_data = response.metadata.get("visualization") if response.metadata else None
                        if viz_data:
                            await websocket.send_json({
                                "type": "visualization",
                                "data": viz_data,
                                "metadata": {
                                    "phase": response.phase,
                                }
                            })
                            logger.info(f"✓ Sent visualization: {viz_data.get('title', 'Unknown')}")
                    
                    elif response.event == "goals_table":
                        # Send goals table event
                        table_data = response.metadata.get("goals_table") if response.metadata else None
                        if table_data:
                            await websocket.send_json({
                                "type": "goals_table",
                                "data": table_data,
                                "metadata": {
                                    "phase": response.phase,
                                }
                            })
                            logger.info(f"✓ Sent goals table")
                    
                    elif response.event == "phase_transition":
                        # Phase transition event
                        workflow.session_state["current_phase"] = response.phase
                        current_phase = response.phase
                        if response.content:
                            await websocket.send_json({
                                "type": "agent_response",
                                "content": response.content,
                                "is_complete": True,
                                "metadata": {
                                    "phase": response.phase,
                                }
                            })
                    
                    elif response.content and response.content.strip():
                        # Regular agent response
                        await websocket.send_json({
                            "type": "agent_response",
                            "content": response.content,
                            "is_complete": True,
                            "metadata": {
                                "phase": response.phase,
                                "conversation_turn": workflow.session_state.get("conversation_turns", 0)
                            }
                        })
                
                # Send processing complete
                if current_phase in ["goal_strategy", "deep_dive"]:
                    await websocket.send_json({
                        "type": "processing",
                        "status": False,
                        "message": "Analysis complete"
                    })
            
            # Send profile update (only for iterative_discovery phase)
            if current_phase == "iterative_discovery":
                # Build complete profile update with all required fields
                discovered_facts = workflow.session_state.get("discovered_facts", {})
                discovered_goals = workflow.session_state.get("discovered_goals", [])
                goals_with_timelines = workflow.session_state.get("goals_with_timelines", [])
                
                # Calculate financial metrics
                facts_count = len([k for k, v in discovered_facts.items() if v is not None and v != ""]) if discovered_facts else 0
                completion = min(100, int((facts_count / 25) * 100)) if facts_count > 0 else 0
                
                total_assets = (
                    discovered_facts.get("total_assets", 0) or 
                    sum([
                        discovered_facts.get("savings", 0) or 0,
                        discovered_facts.get("superannuation_balance", 0) or 0,
                        discovered_facts.get("property_value", 0) or 0,
                        discovered_facts.get("investments_value", 0) or 0,
                    ])
                ) if discovered_facts else 0
                
                total_liabilities = sum([
                    discovered_facts.get("home_loan_amount", 0) or 0,
                    discovered_facts.get("car_loan_amount", 0) or 0,
                    discovered_facts.get("personal_loans_amount", 0) or 0,
                    discovered_facts.get("credit_card_debt", 0) or 0,
                ]) if discovered_facts else 0
                
                cash_balance = (discovered_facts.get("savings", 0) or discovered_facts.get("cash_balance", 0)) if discovered_facts else 0
                net_worth = total_assets - total_liabilities
                
                # Build goals array in format expected by frontend (Goal[])
                goals_array = []
                # Add goals from goals_with_timelines (more complete)
                for g in goals_with_timelines:
                    if g and g.description:
                        # Determine status based on goal completeness
                        status = "not_started"
                        if g.timeline_years and g.amount:
                            status = "discussing"
                        if g.priority:
                            status = "started"
                        
                        goals_array.append({
                            "description": g.description,
                            "timeline_years": g.timeline_years,
                            "amount": g.amount,
                            "priority": "High" if g.priority == 1 else "Medium" if g.priority == 2 else "Low" if g.priority else None,
                            "motivation": g.motivation,
                            "source": "user_stated",  # Goals with timelines are user-stated
                            "status": status,
                        })
                # Add discovered goals that aren't in goals_with_timelines yet
                for goal_desc in discovered_goals:
                    if not any(g.get("description") == goal_desc for g in goals_array):
                        # Check if this goal was discovered by agent (not in user-stated list)
                        is_discovered = goal_desc not in [g.description for g in goals_with_timelines if g and g.description]
                        goals_array.append({
                            "description": goal_desc,
                            "timeline_years": None,
                            "amount": None,
                            "priority": None,
                            "motivation": None,
                            "source": "agent_discovered" if is_discovered else "user_stated",
                            "status": "not_started",
                        })
                
                # Build assets array from discovered facts
                assets_array = []
                if discovered_facts:
                    if discovered_facts.get("savings"):
                        assets_array.append({
                            "asset_type": "cash",
                            "description": "Savings",
                            "value": discovered_facts.get("savings", 0),
                            "institution": None,
                        })
                    if discovered_facts.get("property_value"):
                        assets_array.append({
                            "asset_type": "property",
                            "description": "Property",
                            "value": discovered_facts.get("property_value", 0),
                            "institution": None,
                        })
                    if discovered_facts.get("investments_value"):
                        assets_array.append({
                            "asset_type": "investment",
                            "description": "Investments",
                            "value": discovered_facts.get("investments_value", 0),
                            "institution": None,
                        })
                
                # Build liabilities array from discovered facts
                liabilities_array = []
                if discovered_facts:
                    if discovered_facts.get("home_loan_amount"):
                        liabilities_array.append({
                            "liability_type": "mortgage",
                            "description": "Home Loan",
                            "amount": discovered_facts.get("home_loan_amount", 0),
                            "monthly_payment": discovered_facts.get("home_loan_monthly_payment"),
                            "interest_rate": discovered_facts.get("home_loan_interest_rate"),
                            "institution": None,
                        })
                    if discovered_facts.get("car_loan_amount"):
                        liabilities_array.append({
                            "liability_type": "car_loan",
                            "description": "Car Loan",
                            "amount": discovered_facts.get("car_loan_amount", 0),
                            "monthly_payment": discovered_facts.get("car_loan_emi"),
                            "interest_rate": discovered_facts.get("car_loan_interest_rate"),
                            "institution": None,
                        })
                    if discovered_facts.get("personal_loans_amount"):
                        liabilities_array.append({
                            "liability_type": "personal_loan",
                            "description": "Personal Loan",
                            "amount": discovered_facts.get("personal_loans_amount", 0),
                            "monthly_payment": None,
                            "interest_rate": None,
                            "institution": None,
                        })
                    if discovered_facts.get("credit_card_debt"):
                        liabilities_array.append({
                            "liability_type": "credit_card",
                            "description": "Credit Card Debt",
                            "amount": discovered_facts.get("credit_card_debt", 0),
                            "monthly_payment": None,
                            "interest_rate": None,
                            "institution": None,
                        })
                
                # Build superannuation array
                superannuation_array = []
                if discovered_facts and discovered_facts.get("superannuation_balance"):
                    superannuation_array.append({
                        "fund_name": "Superannuation",
                        "balance": discovered_facts.get("superannuation_balance", 0),
                        "contribution_rate": discovered_facts.get("superannuation_contribution_rate"),
                        "account_type": None,
                    })
                
                # Build personal_info section from discovered_facts
                personal_info = {}
                if discovered_facts:
                    # Personal details
                    if discovered_facts.get("age") is not None:
                        personal_info["age"] = discovered_facts["age"]
                    if discovered_facts.get("marital_status"):
                        personal_info["marital_status"] = discovered_facts["marital_status"]
                    elif discovered_facts.get("family_status"):
                        personal_info["marital_status"] = discovered_facts["family_status"]
                    if discovered_facts.get("location"):
                        personal_info["location"] = discovered_facts["location"]
                    if discovered_facts.get("occupation"):
                        personal_info["occupation"] = discovered_facts["occupation"]
                    if discovered_facts.get("employment_status"):
                        personal_info["employment_status"] = discovered_facts["employment_status"]
                    
                    # Partner details
                    if discovered_facts.get("partner_occupation"):
                        personal_info["partner_occupation"] = discovered_facts["partner_occupation"]
                    if discovered_facts.get("partner_income") is not None:
                        personal_info["partner_income"] = discovered_facts["partner_income"]
                    if discovered_facts.get("partner_employment_status"):
                        personal_info["partner_employment_status"] = discovered_facts["partner_employment_status"]
                    
                    # Family details
                    if discovered_facts.get("dependents") is not None:
                        personal_info["dependents"] = discovered_facts["dependents"]
                    if discovered_facts.get("children_count") is not None:
                        personal_info["children_count"] = discovered_facts["children_count"]
                    if discovered_facts.get("children_ages"):
                        personal_info["children_ages"] = discovered_facts["children_ages"]
                    if discovered_facts.get("children_status"):
                        personal_info["children_status"] = discovered_facts["children_status"]
                
                # Build financial_details section
                financial_details = {}
                if discovered_facts:
                    if discovered_facts.get("emergency_fund_months") is not None:
                        financial_details["emergency_fund_months"] = discovered_facts["emergency_fund_months"]
                    if discovered_facts.get("account_type"):
                        financial_details["account_type"] = discovered_facts["account_type"]
                    elif discovered_facts.get("banking_setup"):
                        financial_details["account_type"] = discovered_facts["banking_setup"]
                
                # Build insurance array from discovered_facts
                insurance_array = []
                if discovered_facts:
                    if discovered_facts.get("life_insurance_type") or discovered_facts.get("life_insurance_amount"):
                        insurance_array.append({
                            "insurance_type": "life",
                            "provider": None,
                            "coverage_amount": discovered_facts.get("life_insurance_amount"),
                            "monthly_premium": None,
                        })
                    if discovered_facts.get("health_insurance") or discovered_facts.get("health_insurance_status"):
                        insurance_array.append({
                            "insurance_type": "health",
                            "provider": None,
                            "coverage_amount": None,
                            "monthly_premium": None,
                        })
                    if discovered_facts.get("income_protection") or discovered_facts.get("income_protection_status"):
                        insurance_array.append({
                            "insurance_type": "income_protection",
                            "provider": None,
                            "coverage_amount": None,
                            "monthly_premium": None,
                        })
                
                # Send complete profile update (merge all updates into one)
                if discovered_facts or discovered_goals or goals_with_timelines:
                    await websocket.send_json({
                        "type": "profile_update",
                        "profile": {
                            # Required arrays
                            "goals": goals_array,
                            "assets": assets_array,
                            "liabilities": liabilities_array,
                            "superannuation": superannuation_array,
                            "insurance": insurance_array,
                            # Computed fields
                            "net_worth": net_worth,
                            "total_assets": total_assets,
                            "cash_balance": cash_balance,
                            "total_liabilities": total_liabilities,
                            # Additional financial fields
                            "income": discovered_facts.get("income") if discovered_facts else None,
                            "monthly_income": discovered_facts.get("monthly_income") if discovered_facts else None,
                            "expenses": discovered_facts.get("monthly_living_expenses") or discovered_facts.get("expenses") if discovered_facts else None,
                            # Personal information
                            "personal_info": personal_info if personal_info else None,
                            # Financial details
                            "financial_details": financial_details if financial_details else None,
                        },
                        "metadata": {
                            "phase": current_phase,
                            "discovered_facts": discovered_facts,  # Send ALL discovered_facts
                            "completeness": completion,
                            "facts_collected": facts_count,
                        }
                    })
                    logger.info(f"✓ Sent complete profile update: assets=${total_assets}, liabilities=${total_liabilities}, net_worth=${net_worth}, goals={len(goals_array)}, completion={completion}%")
            
            logger.info(f"Sent response to user {user_id} (phase: {current_phase})")
            
        except Exception as e:
            logger.error(f"Error processing message for user {user_id}: {e}", exc_info=True)
            
            # Send error response
            await websocket.send_json({
                "type": "agent_response",
                "content": "I apologize, but I encountered an error processing your message. Could you please rephrase that?",
                "is_complete": True,
                "metadata": {
                    "error": str(e),
                    "phase": workflow.session_state.get("current_phase", "unknown")
                }
            })
    
    def get_workflow_state(self, user_id: int) -> Dict[str, Any]:
        """
        Get current workflow state for user.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with workflow state
        """
        workflow = self.get_workflow(user_id)
        
        # Initialize session_state if None
        if workflow.session_state is None:
            workflow.session_state = {}
        
        return {
            "current_phase": workflow.session_state.get("current_phase", "life_discovery"),
            "conversation_turns": workflow.session_state.get("conversation_turns", 0),
            "life_context": workflow.session_state.get("life_context", {}),
            "confirmed_goals": workflow.session_state.get("confirmed_goals", []),
            "goals_with_timelines": workflow.session_state.get("goals_with_timelines", []),
            "financial_profile": workflow.session_state.get("financial_profile", {}),
            "completeness_score": workflow.session_state.get("completeness_score", 0),
            "selected_goal_id": workflow.session_state.get("selected_goal_id"),
            "phase_transitions": workflow.session_state.get("phase_transitions", []),
        }
    
    async def send_greeting(self, websocket: WebSocket):
        """
        Send initial greeting message.
        
        Args:
            websocket: WebSocket connection
        """
        await websocket.send_json({
            "type": "greeting",
            "message": "Hi! I'm your personal financial advisor. I'm here to help you understand your financial situation and create a plan to achieve your goals. To give you the best advice, I'd love to learn a bit about you first. What stage of life are you in?",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    async def send_phase_summary(self, websocket: WebSocket, user_id: int):
        """
        Send summary of current workflow phase and progress.
        
        Args:
            websocket: WebSocket connection
            user_id: User ID
        """
        state = self.get_workflow_state(user_id)
        
        phase_descriptions = {
            "iterative_discovery": "Getting to know you and building your financial goals together",
            "goal_strategy": "Reviewing all your goals, educating you on options, and collaboratively planning priorities",
            "deep_dive": "Creating detailed action plan for your selected goal"
        }
        
        await websocket.send_json({
            "type": "phase_summary",
            "current_phase": state["current_phase"],
            "phase_description": phase_descriptions.get(state["current_phase"], "Processing"),
            "progress": {
                "life_context_complete": bool(state.get("life_context")),
                "goals_discovered": len(state.get("confirmed_goals", [])),
                "goals_with_timelines": len(state.get("goals_with_timelines", [])),
                "financial_completeness": state.get("completeness_score", 0),
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

