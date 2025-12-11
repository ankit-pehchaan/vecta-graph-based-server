"""Remove financial_profiles table, add superannuation table, link all to users

Revision ID: 004
Revises: 003
Create Date: 2025-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add financial fields to users table
    op.add_column('users', sa.Column('income', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('monthly_income', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('expenses', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('risk_tolerance', sa.String(20), nullable=True))
    op.add_column('users', sa.Column('financial_stage', sa.String(100), nullable=True))
    
    # Step 2: Add user_id column to child tables (nullable initially for migration)
    op.add_column('goals', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('assets', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('liabilities', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('insurance', sa.Column('user_id', sa.Integer(), nullable=True))
    
    # Step 3: Migrate data from financial_profiles to users and update child tables
    # Update users with financial data from financial_profiles (matching by email)
    op.execute("""
        UPDATE users u
        SET 
            income = fp.income,
            monthly_income = fp.monthly_income,
            expenses = fp.expenses,
            risk_tolerance = fp.risk_tolerance,
            financial_stage = fp.financial_stage
        FROM financial_profiles fp
        WHERE u.email = fp.username
    """)
    
    # Update child tables to use user_id instead of profile_id
    op.execute("""
        UPDATE goals g
        SET user_id = u.id
        FROM financial_profiles fp, users u
        WHERE g.profile_id = fp.id AND fp.username = u.email
    """)
    
    op.execute("""
        UPDATE assets a
        SET user_id = u.id
        FROM financial_profiles fp, users u
        WHERE a.profile_id = fp.id AND fp.username = u.email
    """)
    
    op.execute("""
        UPDATE liabilities l
        SET user_id = u.id
        FROM financial_profiles fp, users u
        WHERE l.profile_id = fp.id AND fp.username = u.email
    """)
    
    op.execute("""
        UPDATE insurance i
        SET user_id = u.id
        FROM financial_profiles fp, users u
        WHERE i.profile_id = fp.id AND fp.username = u.email
    """)
    
    # Step 4: Create superannuation table
    op.create_table(
        'superannuation',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fund_name', sa.String(255), nullable=False),
        sa.Column('account_number', sa.String(100), nullable=True),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('employer_contribution_rate', sa.Float(), nullable=True),  # percentage
        sa.Column('personal_contribution_rate', sa.Float(), nullable=True),  # percentage
        sa.Column('investment_option', sa.String(100), nullable=True),  # e.g., "Balanced", "Growth", "Conservative"
        sa.Column('insurance_death', sa.Float(), nullable=True),  # Death cover amount
        sa.Column('insurance_tpd', sa.Float(), nullable=True),  # TPD cover amount
        sa.Column('insurance_income', sa.Float(), nullable=True),  # Income protection cover
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Step 5: Migrate superannuation data from financial_profiles to new table
    # Create superannuation records from the scalar values in financial_profiles
    op.execute("""
        INSERT INTO superannuation (user_id, fund_name, balance, created_at, updated_at)
        SELECT u.id, 'Primary Super Fund', fp.superannuation, NOW(), NOW()
        FROM financial_profiles fp
        JOIN users u ON fp.username = u.email
        WHERE fp.superannuation IS NOT NULL AND fp.superannuation > 0
    """)
    
    # Step 6: Migrate cash_balance to assets table
    op.execute("""
        INSERT INTO assets (user_id, asset_type, description, value, created_at)
        SELECT u.id, 'cash', 'Cash Balance', fp.cash_balance, NOW()
        FROM financial_profiles fp
        JOIN users u ON fp.username = u.email
        WHERE fp.cash_balance IS NOT NULL AND fp.cash_balance > 0
    """)
    
    # Step 7: Drop old foreign keys and profile_id columns from child tables
    op.drop_constraint('goals_profile_id_fkey', 'goals', type_='foreignkey')
    op.drop_column('goals', 'profile_id')
    
    op.drop_constraint('assets_profile_id_fkey', 'assets', type_='foreignkey')
    op.drop_column('assets', 'profile_id')
    
    op.drop_constraint('liabilities_profile_id_fkey', 'liabilities', type_='foreignkey')
    op.drop_column('liabilities', 'profile_id')
    
    op.drop_constraint('insurance_profile_id_fkey', 'insurance', type_='foreignkey')
    op.drop_column('insurance', 'profile_id')
    
    # Step 8: Make user_id NOT NULL and add foreign keys
    op.alter_column('goals', 'user_id', nullable=False)
    op.create_foreign_key('goals_user_id_fkey', 'goals', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    op.alter_column('assets', 'user_id', nullable=False)
    op.create_foreign_key('assets_user_id_fkey', 'assets', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    op.alter_column('liabilities', 'user_id', nullable=False)
    op.create_foreign_key('liabilities_user_id_fkey', 'liabilities', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    op.alter_column('insurance', 'user_id', nullable=False)
    op.create_foreign_key('insurance_user_id_fkey', 'insurance', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    # Step 9: Drop financial_profiles table
    op.drop_index('ix_financial_profiles_username', table_name='financial_profiles')
    op.drop_table('financial_profiles')


def downgrade() -> None:
    # Recreate financial_profiles table
    op.create_table(
        'financial_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('income', sa.Float(), nullable=True),
        sa.Column('monthly_income', sa.Float(), nullable=True),
        sa.Column('expenses', sa.Float(), nullable=True),
        sa.Column('cash_balance', sa.Float(), nullable=True),
        sa.Column('superannuation', sa.Float(), nullable=True),
        sa.Column('risk_tolerance', sa.String(length=20), nullable=True),
        sa.Column('financial_stage', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_financial_profiles_username', 'financial_profiles', ['username'], unique=True)
    
    # Add profile_id back to child tables
    op.add_column('goals', sa.Column('profile_id', sa.Integer(), nullable=True))
    op.add_column('assets', sa.Column('profile_id', sa.Integer(), nullable=True))
    op.add_column('liabilities', sa.Column('profile_id', sa.Integer(), nullable=True))
    op.add_column('insurance', sa.Column('profile_id', sa.Integer(), nullable=True))
    
    # Drop user_id foreign keys and columns
    op.drop_constraint('goals_user_id_fkey', 'goals', type_='foreignkey')
    op.drop_column('goals', 'user_id')
    
    op.drop_constraint('assets_user_id_fkey', 'assets', type_='foreignkey')
    op.drop_column('assets', 'user_id')
    
    op.drop_constraint('liabilities_user_id_fkey', 'liabilities', type_='foreignkey')
    op.drop_column('liabilities', 'user_id')
    
    op.drop_constraint('insurance_user_id_fkey', 'insurance', type_='foreignkey')
    op.drop_column('insurance', 'user_id')
    
    # Drop superannuation table
    op.drop_table('superannuation')
    
    # Remove financial columns from users
    op.drop_column('users', 'financial_stage')
    op.drop_column('users', 'risk_tolerance')
    op.drop_column('users', 'expenses')
    op.drop_column('users', 'monthly_income')
    op.drop_column('users', 'income')

