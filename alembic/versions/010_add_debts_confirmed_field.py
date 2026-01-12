"""add_debts_confirmed_field

Revision ID: 010
Revises: 009
Create Date: 2026-01-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add debts_confirmed field to persist user's confirmation that they have no other debts
    op.add_column('users', sa.Column('debts_confirmed', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'debts_confirmed')
