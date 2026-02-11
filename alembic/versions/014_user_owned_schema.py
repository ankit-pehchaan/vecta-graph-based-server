"""User-owned data schema

Revision ID: 014
Revises: None
Create Date: 2026-01-24

Creates the user-owned normalized schema:
- users (extended from auth)
- user_profiles (scalar fields from ALL nodes: Personal, Income, Savings, Loan, Insurance, Marriage, Dependents, Retirement)
- income_entries, expense_entries, asset_entries, liability_entries, insurance_entries
- user_goals
- sessions, conversation_messages, asked_questions
- auth_sessions, auth_verifications
- field_history

Design Principles:
1. Scalar fields -> user_profiles (1:1 with user)
2. Portfolio/dict fields -> separate entry tables (1:N with user)
3. All tables have user_id FK with CASCADE delete
4. Entry tables use UNIQUE constraints for upsert support
5. field_history tracks all changes for audit/temporal queries
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, None] = None  # Base migration for fresh database
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==========================================================================
    # USERS TABLE - Authentication and identity
    # ==========================================================================
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('hashed_password', sa.Text(), nullable=True),
        sa.Column('oauth_provider', sa.String(50), nullable=True),
        sa.Column('account_status', sa.String(20), default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ==========================================================================
    # USER_PROFILES TABLE - All scalar fields from all nodes (1:1 with users)
    # ==========================================================================
    op.create_table(
        'user_profiles',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        
        # ------------------------------------------------------------------
        # Personal node fields
        # ------------------------------------------------------------------
        sa.Column('age', sa.Integer(), nullable=True),
        sa.Column('occupation', sa.String(255), nullable=True),
        sa.Column('employment_type', sa.String(50), nullable=True),
        sa.Column('marital_status', sa.String(20), nullable=True),
        sa.Column('health_conditions', ARRAY(sa.Text()), nullable=True),
        
        # ------------------------------------------------------------------
        # Income node scalar fields (portfolio in income_entries)
        # ------------------------------------------------------------------
        sa.Column('primary_income_type', sa.String(50), nullable=True),
        sa.Column('is_stable', sa.Boolean(), nullable=True),
        
        # ------------------------------------------------------------------
        # Savings node fields
        # ------------------------------------------------------------------
        sa.Column('total_savings', sa.Numeric(15, 2), nullable=True),
        sa.Column('emergency_fund_months', sa.Integer(), nullable=True),
        
        # ------------------------------------------------------------------
        # Loan node scalar fields (portfolio in liability_entries)
        # ------------------------------------------------------------------
        sa.Column('has_debt', sa.Boolean(), nullable=True),
        
        # ------------------------------------------------------------------
        # Insurance node scalar fields (portfolio in insurance_entries)
        # ------------------------------------------------------------------
        sa.Column('has_life_insurance', sa.Boolean(), nullable=True),
        sa.Column('has_tpd_insurance', sa.Boolean(), nullable=True),
        sa.Column('has_income_protection', sa.Boolean(), nullable=True),
        sa.Column('has_private_health', sa.Boolean(), nullable=True),
        sa.Column('spouse_has_life_insurance', sa.Boolean(), nullable=True),
        sa.Column('spouse_has_income_protection', sa.Boolean(), nullable=True),
        
        # ------------------------------------------------------------------
        # Marriage node fields (spouse financial details)
        # ------------------------------------------------------------------
        sa.Column('spouse_age', sa.Integer(), nullable=True),
        sa.Column('spouse_employment_type', sa.String(50), nullable=True),
        sa.Column('spouse_income_annual', sa.Numeric(15, 2), nullable=True),
        
        # ------------------------------------------------------------------
        # Dependents node fields
        # ------------------------------------------------------------------
        sa.Column('number_of_children', sa.Integer(), nullable=True),
        sa.Column('children_ages', ARRAY(sa.Integer()), nullable=True),
        sa.Column('annual_education_cost', sa.Numeric(15, 2), nullable=True),
        sa.Column('child_pathway', sa.String(50), nullable=True),
        sa.Column('education_funding_preference', sa.String(50), nullable=True),
        sa.Column('supporting_parents', sa.Boolean(), nullable=True),
        sa.Column('monthly_parent_support', sa.Numeric(15, 2), nullable=True),
        
        # ------------------------------------------------------------------
        # Retirement node fields
        # ------------------------------------------------------------------
        sa.Column('super_balance', sa.Numeric(15, 2), nullable=True),
        sa.Column('super_account_type', sa.String(50), nullable=True),
        sa.Column('employer_contribution_rate', sa.Numeric(5, 4), nullable=True),
        sa.Column('salary_sacrifice_monthly', sa.Numeric(15, 2), nullable=True),
        sa.Column('personal_contribution_monthly', sa.Numeric(15, 2), nullable=True),
        sa.Column('spouse_super_balance', sa.Numeric(15, 2), nullable=True),
        sa.Column('target_retirement_age', sa.Integer(), nullable=True),
        sa.Column('target_retirement_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('investment_option', sa.String(50), nullable=True),
        
        # ------------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------------
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create income_entries table
    op.create_table(
        'income_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('income_type', sa.String(50), nullable=False),
        sa.Column('annual_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'income_type', name='uq_income_user_type'),
    )

    # Create expense_entries table
    op.create_table(
        'expense_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('monthly_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'category', name='uq_expense_user_category'),
    )

    # Create asset_entries table
    op.create_table(
        'asset_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('asset_category', sa.String(50), nullable=False),
        sa.Column('current_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'asset_category', name='uq_asset_user_category'),
    )

    # Create liability_entries table
    op.create_table(
        'liability_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('liability_type', sa.String(50), nullable=False),
        sa.Column('outstanding_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('monthly_payment', sa.Numeric(15, 2), nullable=True),
        sa.Column('interest_rate', sa.Numeric(6, 4), nullable=True),
        sa.Column('remaining_term_months', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'liability_type', name='uq_liability_user_type'),
    )

    # Create insurance_entries table
    op.create_table(
        'insurance_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('insurance_type', sa.String(50), nullable=False),
        sa.Column('covered_person', sa.String(20), nullable=True),
        sa.Column('held_through', sa.String(20), nullable=True),
        sa.Column('coverage_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('premium_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('premium_frequency', sa.String(20), nullable=True),
        sa.Column('waiting_period_weeks', sa.Integer(), nullable=True),
        sa.Column('benefit_period_months', sa.Integer(), nullable=True),
        sa.Column('excess_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'insurance_type', name='uq_insurance_user_type'),
    )

    # Create user_goals table
    op.create_table(
        'user_goals',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('goal_id', sa.String(100), nullable=False),
        sa.Column('goal_type', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='possible', index=True),
        sa.Column('target_amount', sa.Numeric(15, 2), nullable=True),
        sa.Column('target_year', sa.Integer(), nullable=True),
        sa.Column('timeline_years', sa.Integer(), nullable=True),
        sa.Column('target_months', sa.Integer(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Numeric(3, 2), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('deduced_from', ARRAY(sa.Text()), nullable=True),
        sa.Column('funding_method', sa.String(50), nullable=True),
        sa.Column('confirmed_via', sa.String(50), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('user_id', 'goal_id', name='uq_goal_user_goalid'),
    )

    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('visited_nodes', ARRAY(sa.Text()), server_default='{}'),
        sa.Column('pending_nodes', ARRAY(sa.Text()), server_default='{}'),
        sa.Column('omitted_nodes', ARRAY(sa.Text()), server_default='{}'),
        sa.Column('rejected_nodes', ARRAY(sa.Text()), server_default='{}'),
        sa.Column('current_node', sa.String(50), nullable=True),
        sa.Column('goal_intake_complete', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_active_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create conversation_messages table
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('extracted_data', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Create asked_questions table
    op.create_table(
        'asked_questions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('node_name', sa.String(50), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('asked_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('session_id', 'node_name', 'field_name', name='uq_asked_session_node_field'),
    )

    # Create auth_sessions table
    op.create_table(
        'auth_sessions',
        sa.Column('refresh_jti', sa.String(255), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('expires_at', sa.Integer(), nullable=False),
        sa.Column('revoked', sa.Boolean(), default=False),
        sa.Column('used', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Create auth_verifications table
    op.create_table(
        'auth_verifications',
        sa.Column('token', sa.String(255), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('hashed_password', sa.Text(), nullable=True),
        sa.Column('otp', sa.String(10), nullable=True),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), default=0),
    )

    # Create field_history table
    op.create_table(
        'field_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('node_name', sa.String(50), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('source', sa.String(50), default='user_input'),
        sa.Column('is_correction', sa.Boolean(), default=False),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Create composite indexes for common queries
    # Note: status index is already created by index=True on the column
    op.create_index('ix_field_history_node_field', 'field_history', ['node_name', 'field_name'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_field_history_node_field', table_name='field_history')

    # Drop tables in reverse order (respect foreign keys)
    op.drop_table('field_history')
    op.drop_table('auth_verifications')
    op.drop_table('auth_sessions')
    op.drop_table('asked_questions')
    op.drop_table('conversation_messages')
    op.drop_table('sessions')
    op.drop_table('user_goals')
    op.drop_table('insurance_entries')
    op.drop_table('liability_entries')
    op.drop_table('asset_entries')
    op.drop_table('expense_entries')
    op.drop_table('income_entries')
    op.drop_table('user_profiles')
    op.drop_table('users')

