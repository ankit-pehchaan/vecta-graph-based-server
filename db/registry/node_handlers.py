"""
Node registry and handlers for mapping GraphMemory nodes to database persistence.

Each handler owns load/save logic for a specific node.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.user import UserProfile
from db.models.entries import (
    IncomeEntry,
    ExpenseEntry,
    AssetEntry,
    LiabilityEntry,
    InsuranceEntry,
)


HistoryCallback = Callable[[Session, int, str, str, Any, Any, bool], None]


class NodeHandler:
    """Base class for node handlers."""

    node_name: str = ""

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        """Load node data for a user from DB."""
        raise NotImplementedError

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        """Save node data to DB."""
        raise NotImplementedError


class PersonalHandler(NodeHandler):
    node_name = "Personal"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        if not profile:
            return None
        data: dict[str, Any] = {}
        if profile.age is not None:
            data["age"] = profile.age
        if profile.occupation:
            data["occupation"] = profile.occupation
        if profile.marital_status:
            data["marital_status"] = profile.marital_status
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        field_map = {
            "age": "age",
            "occupation": "occupation",
            "marital_status": "marital_status",
        }
        for field, attr in field_map.items():
            if field in data:
                old_val = getattr(profile, attr)
                new_val = data[field]
                if old_val != new_val:
                    setattr(profile, attr, new_val)
                    if record_history:
                        record_history_cb(db, user_id, "Personal", field, old_val, new_val, False)


class IncomeHandler(NodeHandler):
    node_name = "Income"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        income_entries = db.execute(
            select(IncomeEntry).where(IncomeEntry.user_id == user_id)
        ).scalars().all()
        if not income_entries and not profile:
            return None
        data: dict[str, Any] = {}
        if income_entries:
            data["income_streams_annual"] = {
                e.income_type: float(e.annual_amount) for e in income_entries
            }
        if profile and profile.income_type:
            data["income_type"] = profile.income_type
        if profile and profile.is_pre_tax is not None:
            data["is_pre_tax"] = profile.is_pre_tax
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        # Scalars
        if "income_type" in data:
            old = profile.income_type
            new = data["income_type"]
            if old != new:
                profile.income_type = new
                if record_history:
                    record_history_cb(db, user_id, "Income", "income_type", old, new, False)
        if "is_pre_tax" in data:
            old = profile.is_pre_tax
            new = data["is_pre_tax"]
            if old != new:
                profile.is_pre_tax = new
                if record_history:
                    record_history_cb(db, user_id, "Income", "is_pre_tax", old, new, False)

        # Portfolio
        if "income_streams_annual" in data:
            streams = data["income_streams_annual"]
            for income_type, amount in streams.items():
                existing = db.execute(
                    select(IncomeEntry).where(
                        IncomeEntry.user_id == user_id,
                        IncomeEntry.income_type == income_type,
                    )
                ).scalar_one_or_none()
                if existing:
                    if float(existing.annual_amount) != float(amount):
                        if record_history:
                            record_history_cb(
                                db, user_id, "Income",
                                f"income_streams_annual.{income_type}",
                                float(existing.annual_amount), float(amount), False
                            )
                        existing.annual_amount = Decimal(str(amount))
                else:
                    db.add(IncomeEntry(
                        user_id=user_id,
                        income_type=income_type,
                        annual_amount=Decimal(str(amount)),
                    ))
                    if record_history:
                        record_history_cb(
                            db, user_id, "Income",
                            f"income_streams_annual.{income_type}",
                            None, float(amount), False
                        )


class ExpensesHandler(NodeHandler):
    node_name = "Expenses"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        expense_entries = db.execute(
            select(ExpenseEntry).where(ExpenseEntry.user_id == user_id)
        ).scalars().all()
        if not expense_entries:
            return None
        return {
            "monthly_expenses": {
                e.category: float(e.monthly_amount) for e in expense_entries
            }
        }

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        if "monthly_expenses" in data:
            expenses = data["monthly_expenses"]
            for category, amount in expenses.items():
                existing = db.execute(
                    select(ExpenseEntry).where(
                        ExpenseEntry.user_id == user_id,
                        ExpenseEntry.category == category,
                    )
                ).scalar_one_or_none()
                if existing:
                    if float(existing.monthly_amount) != float(amount):
                        if record_history:
                            record_history_cb(
                                db, user_id, "Expenses",
                                f"monthly_expenses.{category}",
                                float(existing.monthly_amount), float(amount), False
                            )
                        existing.monthly_amount = Decimal(str(amount))
                else:
                    db.add(ExpenseEntry(
                        user_id=user_id,
                        category=category,
                        monthly_amount=Decimal(str(amount)),
                    ))
                    if record_history:
                        record_history_cb(
                            db, user_id, "Expenses",
                            f"monthly_expenses.{category}",
                            None, float(amount), False
                        )


class SavingsHandler(NodeHandler):
    node_name = "Savings"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        if not profile:
            return None
        if (profile.total_savings is None
                and profile.emergency_fund_months is None
                and profile.offset_balance is None):
            return None
        data: dict[str, Any] = {}
        if profile.total_savings is not None:
            data["total_savings"] = float(profile.total_savings)
        if profile.emergency_fund_months is not None:
            data["emergency_fund_months"] = profile.emergency_fund_months
        if profile.offset_balance is not None:
            data["offset_balance"] = float(profile.offset_balance)
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        if "total_savings" in data:
            old = float(profile.total_savings) if profile.total_savings else None
            new = data["total_savings"]
            if old != new:
                profile.total_savings = Decimal(str(new)) if new is not None else None
                if record_history:
                    record_history_cb(db, user_id, "Savings", "total_savings", old, new, False)
        if "emergency_fund_months" in data:
            old = profile.emergency_fund_months
            new = data["emergency_fund_months"]
            if old != new:
                profile.emergency_fund_months = new
                if record_history:
                    record_history_cb(db, user_id, "Savings", "emergency_fund_months", old, new, False)
        if "offset_balance" in data:
            old = float(profile.offset_balance) if profile.offset_balance else None
            new = data["offset_balance"]
            if old != new:
                profile.offset_balance = Decimal(str(new)) if new is not None else None
                if record_history:
                    record_history_cb(db, user_id, "Savings", "offset_balance", old, new, False)


class AssetsHandler(NodeHandler):
    node_name = "Assets"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        asset_entries = db.execute(
            select(AssetEntry).where(AssetEntry.user_id == user_id)
        ).scalars().all()
        has_scalars = profile and profile.has_property is not None
        if not asset_entries and not has_scalars:
            return None
        data: dict[str, Any] = {}
        if asset_entries:
            data["asset_current_amount"] = {
                e.asset_category: float(e.current_amount) for e in asset_entries
            }
        if profile and profile.has_property is not None:
            data["has_property"] = profile.has_property
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        if "has_property" in data:
            old = profile.has_property
            new = data["has_property"]
            if old != new:
                profile.has_property = new
                if record_history:
                    record_history_cb(db, user_id, "Assets", "has_property", old, new, False)

        if "asset_current_amount" in data:
            assets = data["asset_current_amount"]
            for category, amount in assets.items():
                existing = db.execute(
                    select(AssetEntry).where(
                        AssetEntry.user_id == user_id,
                        AssetEntry.asset_category == category,
                    )
                ).scalar_one_or_none()
                if existing:
                    if float(existing.current_amount) != float(amount):
                        if record_history:
                            record_history_cb(
                                db, user_id, "Assets",
                                f"asset_current_amount.{category}",
                                float(existing.current_amount), float(amount), False
                            )
                        existing.current_amount = Decimal(str(amount))
                else:
                    db.add(AssetEntry(
                        user_id=user_id,
                        asset_category=category,
                        current_amount=Decimal(str(amount)),
                    ))
                    if record_history:
                        record_history_cb(
                            db, user_id, "Assets",
                            f"asset_current_amount.{category}",
                            None, float(amount), False
                        )


class LoanHandler(NodeHandler):
    node_name = "Loan"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        liability_entries = db.execute(
            select(LiabilityEntry).where(LiabilityEntry.user_id == user_id)
        ).scalars().all()
        if not liability_entries and not profile:
            return None
        data: dict[str, Any] = {}
        if liability_entries:
            data["liabilities"] = {
                e.liability_type: {
                    "outstanding_amount": float(e.outstanding_amount) if e.outstanding_amount else None,
                    "monthly_payment": float(e.monthly_payment) if e.monthly_payment else None,
                    "interest_rate": float(e.interest_rate) if e.interest_rate else None,
                    "remaining_term_months": e.remaining_term_months,
                    "repayment_type": e.repayment_type,
                }
                for e in liability_entries
            }
        if profile and profile.has_debt is not None:
            data["has_debt"] = profile.has_debt
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        if "has_debt" in data:
            old = profile.has_debt
            new = data["has_debt"]
            if old != new:
                profile.has_debt = new
                if record_history:
                    record_history_cb(db, user_id, "Loan", "has_debt", old, new, False)

        if "liabilities" in data:
            liabilities = data["liabilities"]
            for liability_type, details in liabilities.items():
                if isinstance(details, dict):
                    existing = db.execute(
                        select(LiabilityEntry).where(
                            LiabilityEntry.user_id == user_id,
                            LiabilityEntry.liability_type == liability_type,
                        )
                    ).scalar_one_or_none()
                    if existing:
                        for field in ["outstanding_amount", "monthly_payment", "interest_rate", "remaining_term_months", "repayment_type"]:
                            if field in details and details[field] is not None:
                                old_val = getattr(existing, field)
                                new_val = details[field]
                                if field in ["outstanding_amount", "monthly_payment", "interest_rate"]:
                                    new_val = Decimal(str(new_val)) if new_val is not None else None
                                if old_val != new_val:
                                    setattr(existing, field, new_val)
                                    if record_history:
                                        record_history_cb(
                                            db, user_id, "Loan",
                                            f"liabilities.{liability_type}.{field}",
                                            float(old_val) if old_val and field != "repayment_type" else old_val,
                                            float(new_val) if new_val and field != "repayment_type" else new_val,
                                            False
                                        )
                    else:
                        entry = LiabilityEntry(
                            user_id=user_id,
                            liability_type=liability_type,
                            outstanding_amount=Decimal(str(details.get("outstanding_amount"))) if details.get("outstanding_amount") else None,
                            monthly_payment=Decimal(str(details.get("monthly_payment"))) if details.get("monthly_payment") else None,
                            interest_rate=Decimal(str(details.get("interest_rate"))) if details.get("interest_rate") else None,
                            remaining_term_months=details.get("remaining_term_months"),
                            repayment_type=details.get("repayment_type"),
                        )
                        db.add(entry)


class InsuranceHandler(NodeHandler):
    node_name = "Insurance"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        insurance_entries = db.execute(
            select(InsuranceEntry).where(InsuranceEntry.user_id == user_id)
        ).scalars().all()
        insurance_scalars = profile and any([
            profile.has_life_insurance is not None,
            profile.has_tpd_insurance is not None,
            profile.has_income_protection is not None,
            profile.has_private_health is not None,
        ])
        if not insurance_entries and not insurance_scalars:
            return None

        data: dict[str, Any] = {}
        if insurance_entries:
            data["coverages"] = {
                e.insurance_type: {
                    "covered_person": e.covered_person,
                    "held_through": e.held_through,
                    "coverage_amount": float(e.coverage_amount) if e.coverage_amount else None,
                    "premium_amount": float(e.premium_amount) if e.premium_amount else None,
                    "premium_frequency": e.premium_frequency,
                }
                for e in insurance_entries
            }
        if profile:
            if profile.has_life_insurance is not None:
                data["has_life_insurance"] = profile.has_life_insurance
            if profile.has_tpd_insurance is not None:
                data["has_tpd_insurance"] = profile.has_tpd_insurance
            if profile.has_income_protection is not None:
                data["has_income_protection"] = profile.has_income_protection
            if profile.has_private_health is not None:
                data["has_private_health"] = profile.has_private_health
            if profile.spouse_has_life_insurance is not None:
                data["spouse_has_life_insurance"] = profile.spouse_has_life_insurance
            if profile.spouse_has_income_protection is not None:
                data["spouse_has_income_protection"] = profile.spouse_has_income_protection
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        scalar_fields = [
            "has_life_insurance", "has_tpd_insurance", "has_income_protection",
            "has_private_health", "spouse_has_life_insurance", "spouse_has_income_protection"
        ]
        for field in scalar_fields:
            if field in data:
                old = getattr(profile, field)
                new = data[field]
                if old != new:
                    setattr(profile, field, new)
                    if record_history:
                        record_history_cb(db, user_id, "Insurance", field, old, new, False)

        if "coverages" in data:
            coverages = data["coverages"]
            for insurance_type, details in coverages.items():
                if isinstance(details, dict):
                    existing = db.execute(
                        select(InsuranceEntry).where(
                            InsuranceEntry.user_id == user_id,
                            InsuranceEntry.insurance_type == insurance_type,
                        )
                    ).scalar_one_or_none()
                    if existing:
                        update_fields = [
                            "covered_person", "held_through", "coverage_amount",
                            "premium_amount", "premium_frequency"
                        ]
                        for field in update_fields:
                            if field in details and details[field] is not None:
                                old_val = getattr(existing, field)
                                new_val = details[field]
                                if field in ["coverage_amount", "premium_amount"]:
                                    new_val = Decimal(str(new_val)) if new_val is not None else None
                                if old_val != new_val:
                                    setattr(existing, field, new_val)
                    else:
                        entry = InsuranceEntry(
                            user_id=user_id,
                            insurance_type=insurance_type,
                            covered_person=details.get("covered_person"),
                            held_through=details.get("held_through"),
                            coverage_amount=Decimal(str(details.get("coverage_amount"))) if details.get("coverage_amount") else None,
                            premium_amount=Decimal(str(details.get("premium_amount"))) if details.get("premium_amount") else None,
                            premium_frequency=details.get("premium_frequency"),
                        )
                        db.add(entry)


class MarriageHandler(NodeHandler):
    """Handler for Marriage node (spouse financial details)."""
    node_name = "Marriage"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        if not profile:
            return None
        data: dict[str, Any] = {}
        if profile.spouse_age is not None:
            data["spouse_age"] = profile.spouse_age
        if profile.spouse_income_annual is not None:
            data["spouse_income_annual"] = float(profile.spouse_income_annual)
        if profile.finances_combined is not None:
            data["finances_combined"] = profile.finances_combined
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        field_map = {
            "spouse_age": ("spouse_age", None),
            "spouse_income_annual": ("spouse_income_annual", Decimal),
            "finances_combined": ("finances_combined", None),
        }
        for field, (attr, converter) in field_map.items():
            if field in data:
                old_val = getattr(profile, attr)
                new_val = data[field]
                if converter and new_val is not None:
                    new_val = converter(str(new_val))
                if old_val != new_val:
                    setattr(profile, attr, new_val)
                    if record_history:
                        record_history_cb(db, user_id, "Marriage", field, old_val, new_val, False)


class DependentsHandler(NodeHandler):
    """Handler for Dependents node (children information)."""
    node_name = "Dependents"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        if not profile:
            return None
        data: dict[str, Any] = {}
        if profile.number_of_children is not None:
            data["number_of_children"] = profile.number_of_children
        if profile.children_ages:
            data["children_ages"] = profile.children_ages
        if profile.annual_education_cost is not None:
            data["annual_education_cost"] = float(profile.annual_education_cost)
        if profile.child_pathway:
            data["child_pathway"] = profile.child_pathway
        if profile.education_funding_preference:
            data["education_funding_preference"] = profile.education_funding_preference
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        field_map = {
            "number_of_children": ("number_of_children", None),
            "children_ages": ("children_ages", None),
            "annual_education_cost": ("annual_education_cost", Decimal),
            "child_pathway": ("child_pathway", None),
            "education_funding_preference": ("education_funding_preference", None),
        }
        for field, (attr, converter) in field_map.items():
            if field in data:
                old_val = getattr(profile, attr)
                new_val = data[field]
                if converter and new_val is not None:
                    new_val = converter(str(new_val))
                if old_val != new_val:
                    setattr(profile, attr, new_val)
                    if record_history:
                        record_history_cb(db, user_id, "Dependents", field, old_val, new_val, False)


class RetirementHandler(NodeHandler):
    """Handler for Retirement node (super and retirement planning)."""
    node_name = "Retirement"

    def load(self, db: Session, user_id: int, profile: UserProfile | None) -> dict[str, Any] | None:
        if not profile:
            return None
        data: dict[str, Any] = {}
        if profile.super_balance is not None:
            data["super_balance"] = float(profile.super_balance)
        if profile.super_account_type:
            data["super_account_type"] = profile.super_account_type
        if profile.employer_contribution_rate is not None:
            data["employer_contribution_rate"] = float(profile.employer_contribution_rate)
        if profile.salary_sacrifice_monthly is not None:
            data["salary_sacrifice_monthly"] = float(profile.salary_sacrifice_monthly)
        if profile.personal_contribution_monthly is not None:
            data["personal_contribution_monthly"] = float(profile.personal_contribution_monthly)
        if profile.spouse_super_balance is not None:
            data["spouse_super_balance"] = float(profile.spouse_super_balance)
        if profile.target_retirement_age is not None:
            data["target_retirement_age"] = profile.target_retirement_age
        if profile.target_retirement_amount is not None:
            data["target_retirement_amount"] = float(profile.target_retirement_amount)
        if profile.investment_option:
            data["investment_option"] = profile.investment_option
        return data or None

    def save(
        self,
        db: Session,
        user_id: int,
        profile: UserProfile,
        data: dict[str, Any],
        record_history: bool,
        record_history_cb: HistoryCallback,
    ) -> None:
        field_map = {
            "super_balance": ("super_balance", Decimal),
            "super_account_type": ("super_account_type", None),
            "employer_contribution_rate": ("employer_contribution_rate", Decimal),
            "salary_sacrifice_monthly": ("salary_sacrifice_monthly", Decimal),
            "personal_contribution_monthly": ("personal_contribution_monthly", Decimal),
            "spouse_super_balance": ("spouse_super_balance", Decimal),
            "target_retirement_age": ("target_retirement_age", None),
            "target_retirement_amount": ("target_retirement_amount", Decimal),
            "investment_option": ("investment_option", None),
        }
        for field, (attr, converter) in field_map.items():
            if field in data:
                old_val = getattr(profile, attr)
                new_val = data[field]
                if converter and new_val is not None:
                    new_val = converter(str(new_val))
                if old_val != new_val:
                    setattr(profile, attr, new_val)
                    if record_history:
                        record_history_cb(db, user_id, "Retirement", field, old_val, new_val, False)


# =============================================================================
# NODE REGISTRY - Maps node names to their handlers
# =============================================================================
NODE_REGISTRY: dict[str, NodeHandler] = {
    PersonalHandler.node_name: PersonalHandler(),
    IncomeHandler.node_name: IncomeHandler(),
    ExpensesHandler.node_name: ExpensesHandler(),
    SavingsHandler.node_name: SavingsHandler(),
    AssetsHandler.node_name: AssetsHandler(),
    LoanHandler.node_name: LoanHandler(),
    InsuranceHandler.node_name: InsuranceHandler(),
    MarriageHandler.node_name: MarriageHandler(),
    DependentsHandler.node_name: DependentsHandler(),
    RetirementHandler.node_name: RetirementHandler(),
}


def get_node_handler(node_name: str) -> NodeHandler | None:
    """Get handler for a node by name. Returns None if not found."""
    return NODE_REGISTRY.get(node_name)
