"""add_visualization_history

Revision ID: 012
Revises: 011
Create Date: 2026-01-19

Adds visualization_history table for:
- Storing all generated visualizations for users
- Tracking helpfulness scores for learning
- Engagement metrics (viewed, interacted)
- Follow-up relationships (parent_viz_id)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'visualization_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('viz_id', sa.String(36), unique=True, nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', sa.String(255), nullable=False, index=True),

        # Visualization type and classification
        sa.Column('viz_type', sa.String(50), nullable=False),
        sa.Column('calc_kind', sa.String(50), nullable=True),

        # Display metadata
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('subtitle', sa.String(500), nullable=True),
        sa.Column('narrative', sa.Text(), nullable=True),

        # Core data (JSON serialized)
        sa.Column('parameters', JSON, nullable=True),
        sa.Column('data', JSON, nullable=True),

        # Scoring and decision metadata
        sa.Column('helpfulness_score', sa.Float(), nullable=True),
        sa.Column('rule_score', sa.Float(), nullable=True),
        sa.Column('llm_score', sa.Float(), nullable=True),
        sa.Column('history_score', sa.Float(), nullable=True),

        # User engagement tracking
        sa.Column('was_viewed', sa.Boolean(), default=False, nullable=False),
        sa.Column('was_interacted', sa.Boolean(), default=False, nullable=False),

        # Follow-up tracking
        sa.Column('parent_viz_id', sa.String(36), nullable=True, index=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create additional index on created_at for time-based queries
    op.create_index('ix_visualization_history_created_at', 'visualization_history', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_visualization_history_created_at', table_name='visualization_history')
    op.drop_table('visualization_history')
