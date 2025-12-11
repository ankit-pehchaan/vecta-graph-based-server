"""Add cash_balance and superannuation columns to financial_profiles

Revision ID: 003
Revises: 002
Create Date: 2025-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cash_balance column
    op.add_column(
        'financial_profiles',
        sa.Column('cash_balance', sa.Float(), nullable=True)
    )
    
    # Add superannuation column
    op.add_column(
        'financial_profiles',
        sa.Column('superannuation', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    # Remove superannuation column
    op.drop_column('financial_profiles', 'superannuation')
    
    # Remove cash_balance column
    op.drop_column('financial_profiles', 'cash_balance')

