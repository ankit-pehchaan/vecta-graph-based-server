"""add_liability_tenure_months

Revision ID: 008
Revises: 007
Create Date: 2026-01-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tenure_months column to liabilities table
    op.add_column('liabilities', sa.Column('tenure_months', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('liabilities', 'tenure_months')
