"""Simplify nodes per CSV questionnaire

Revision ID: 015
Revises: 014
Create Date: 2026-02-09

Changes per CSV questionnaire review:
- Personal: remove employment_type, health_conditions
- Income: remove primary_income_type, is_stable; add income_type, is_pre_tax
- Marriage: remove spouse_employment_type; add finances_combined
- Dependents: remove supporting_parents, monthly_parent_support
- Savings: add offset_balance
- Assets: add has_property
- Liabilities: add repayment_type
- Insurance: remove waiting_period_weeks, benefit_period_months, excess_amount from insurance_entries
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # user_profiles: Remove columns
    # =========================================================================
    op.drop_column("user_profiles", "employment_type")
    op.drop_column("user_profiles", "health_conditions")
    op.drop_column("user_profiles", "primary_income_type")
    op.drop_column("user_profiles", "is_stable")
    op.drop_column("user_profiles", "spouse_employment_type")
    op.drop_column("user_profiles", "supporting_parents")
    op.drop_column("user_profiles", "monthly_parent_support")

    # =========================================================================
    # user_profiles: Add columns
    # =========================================================================
    op.add_column("user_profiles", sa.Column("income_type", sa.String(50), nullable=True))
    op.add_column("user_profiles", sa.Column("is_pre_tax", sa.Boolean(), nullable=True))
    op.add_column("user_profiles", sa.Column("finances_combined", sa.Boolean(), nullable=True))
    op.add_column("user_profiles", sa.Column("offset_balance", sa.Numeric(15, 2), nullable=True))
    op.add_column("user_profiles", sa.Column("has_property", sa.Boolean(), nullable=True))

    # =========================================================================
    # insurance_entries: Remove excessive detail columns
    # =========================================================================
    op.drop_column("insurance_entries", "waiting_period_weeks")
    op.drop_column("insurance_entries", "benefit_period_months")
    op.drop_column("insurance_entries", "excess_amount")

    # =========================================================================
    # liability_entries: Add repayment_type column
    # =========================================================================
    op.add_column("liability_entries", sa.Column("repayment_type", sa.String(20), nullable=True))


def downgrade() -> None:
    # =========================================================================
    # liability_entries: Remove repayment_type
    # =========================================================================
    op.drop_column("liability_entries", "repayment_type")

    # =========================================================================
    # insurance_entries: Restore removed columns
    # =========================================================================
    op.add_column("insurance_entries", sa.Column("waiting_period_weeks", sa.Integer(), nullable=True))
    op.add_column("insurance_entries", sa.Column("benefit_period_months", sa.Integer(), nullable=True))
    op.add_column("insurance_entries", sa.Column("excess_amount", sa.Numeric(15, 2), nullable=True))

    # =========================================================================
    # user_profiles: Remove added columns
    # =========================================================================
    op.drop_column("user_profiles", "has_property")
    op.drop_column("user_profiles", "offset_balance")
    op.drop_column("user_profiles", "finances_combined")
    op.drop_column("user_profiles", "is_pre_tax")
    op.drop_column("user_profiles", "income_type")

    # =========================================================================
    # user_profiles: Restore removed columns
    # =========================================================================
    op.add_column("user_profiles", sa.Column("employment_type", sa.String(50), nullable=True))
    op.add_column("user_profiles", sa.Column("health_conditions", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("user_profiles", sa.Column("primary_income_type", sa.String(50), nullable=True))
    op.add_column("user_profiles", sa.Column("is_stable", sa.Boolean(), nullable=True))
    op.add_column("user_profiles", sa.Column("spouse_employment_type", sa.String(50), nullable=True))
    op.add_column("user_profiles", sa.Column("supporting_parents", sa.Boolean(), nullable=True))
    op.add_column("user_profiles", sa.Column("monthly_parent_support", sa.Numeric(15, 2), nullable=True))
