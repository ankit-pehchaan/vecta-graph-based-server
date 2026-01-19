"""remove_duplicate_savings_fields

Revision ID: 013
Revises: 012
Create Date: 2026-01-19

Removes duplicate savings/emergency_fund scalar fields from users table.
These values are now stored ONLY in the assets table with asset_type='savings'
and asset_type='emergency_fund' respectively.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the duplicate scalar columns from users table
    # Data is now stored only in assets table
    op.drop_column('users', 'savings')
    op.drop_column('users', 'emergency_fund')
    op.drop_column('users', 'savings_emergency_linked')


def downgrade() -> None:
    # Re-add columns if needed for rollback
    op.add_column('users', sa.Column('savings', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('emergency_fund', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('savings_emergency_linked', sa.Boolean(), nullable=True))
