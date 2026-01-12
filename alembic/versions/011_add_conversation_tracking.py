"""add_conversation_tracking

Revision ID: 011
Revises: 010
Create Date: 2026-01-12

Adds fields for:
- conversation_history: Recent conversation turns for context
- field_states: Track state of each field (answered, skipped, not_provided)
- savings_emergency_linked: Boolean to indicate if savings IS the emergency fund
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add conversation_history to store recent turns for context
    # Format: [{"role": "user"|"assistant", "content": "...", "timestamp": "..."}, ...]
    op.add_column('users', sa.Column('conversation_history', JSON, nullable=True))

    # Add field_states to track completion state of each field
    # Format: {"age": "answered", "savings": "skipped", "super_balance": "not_provided", ...}
    op.add_column('users', sa.Column('field_states', JSON, nullable=True))

    # Add flag to indicate if savings and emergency fund are the same pool of money
    op.add_column('users', sa.Column('savings_emergency_linked', sa.Boolean(), nullable=True, server_default='false'))

    # Add last_correction to track recent corrections for context
    # Format: {"field": "monthly_income", "old_value": 5000, "new_value": 10000, "timestamp": "..."}
    op.add_column('users', sa.Column('last_correction', JSON, nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_correction')
    op.drop_column('users', 'savings_emergency_linked')
    op.drop_column('users', 'field_states')
    op.drop_column('users', 'conversation_history')
