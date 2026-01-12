"""add_conversation_state_fields

Revision ID: 009
Revises: 008
Create Date: 2026-01-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additional financial fields (from store_manager)
    op.add_column('users', sa.Column('savings', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('emergency_fund', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('job_stability', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('dependents', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('timeline', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('target_amount', sa.Float(), nullable=True))

    # Conversation state fields (for tool-based agent)
    op.add_column('users', sa.Column('user_goal', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('goal_classification', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('conversation_phase', sa.String(50), nullable=True, server_default='initial'))
    op.add_column('users', sa.Column('stated_goals', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('discovered_goals', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('critical_concerns', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('required_fields', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('missing_fields', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('pending_probe', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('risk_profile', sa.JSON(), nullable=True))


def downgrade() -> None:
    # Conversation state fields
    op.drop_column('users', 'risk_profile')
    op.drop_column('users', 'pending_probe')
    op.drop_column('users', 'missing_fields')
    op.drop_column('users', 'required_fields')
    op.drop_column('users', 'critical_concerns')
    op.drop_column('users', 'discovered_goals')
    op.drop_column('users', 'stated_goals')
    op.drop_column('users', 'conversation_phase')
    op.drop_column('users', 'goal_classification')
    op.drop_column('users', 'user_goal')

    # Additional financial fields
    op.drop_column('users', 'target_amount')
    op.drop_column('users', 'timeline')
    op.drop_column('users', 'dependents')
    op.drop_column('users', 'job_stability')
    op.drop_column('users', 'emergency_fund')
    op.drop_column('users', 'savings')
