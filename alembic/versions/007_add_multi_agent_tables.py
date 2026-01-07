"""add_multi_agent_tables

Revision ID: 007
Revises: 006
Create Date: 2025-01-XX

Adds tables for multi-agent financial advisor system:
- agent_sessions: Track conversation sessions
- goal_states: Track goal progress and priority
- agent_analyses: Store specialist analysis results
- visualizations: Store generated visualization specs
- holistic_snapshots: Store complete financial snapshots
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_sessions table
    op.create_table(
        'agent_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('phase', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_sessions_user_id', 'agent_sessions', ['user_id'])
    op.create_index('ix_agent_sessions_session_id', 'agent_sessions', ['session_id'])
    op.create_index('ix_agent_sessions_phase', 'agent_sessions', ['phase'])

    # goal_states table
    op.create_table(
        'goal_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('priority_rank', sa.Integer(), nullable=True),
        sa.Column('priority_rationale', sa.Text(), nullable=True),
        sa.Column('completeness_score', sa.Integer(), nullable=True),
        sa.Column('next_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_goal_states_user_id', 'goal_states', ['user_id'])
    op.create_index('ix_goal_states_goal_id', 'goal_states', ['goal_id'])
    op.create_index('ix_goal_states_status', 'goal_states', ['status'])

    # agent_analyses table
    op.create_table(
        'agent_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=True),
        sa.Column('agent_type', sa.String(length=50), nullable=False),
        sa.Column('analysis_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('recommendations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_analyses_user_id', 'agent_analyses', ['user_id'])
    op.create_index('ix_agent_analyses_goal_id', 'agent_analyses', ['goal_id'])
    op.create_index('ix_agent_analyses_agent_type', 'agent_analyses', ['agent_type'])
    op.create_index('ix_agent_analyses_created_at', 'agent_analyses', ['created_at'])

    # visualizations table
    op.create_table(
        'visualizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=True),
        sa.Column('viz_type', sa.String(length=50), nullable=False),
        sa.Column('spec_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_visualizations_user_id', 'visualizations', ['user_id'])
    op.create_index('ix_visualizations_goal_id', 'visualizations', ['goal_id'])
    op.create_index('ix_visualizations_created_at', 'visualizations', ['created_at'])

    # holistic_snapshots table
    op.create_table(
        'holistic_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('gaps_identified', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('opportunities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('risks', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_holistic_snapshots_user_id', 'holistic_snapshots', ['user_id'])
    op.create_index('ix_holistic_snapshots_created_at', 'holistic_snapshots', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_holistic_snapshots_created_at', table_name='holistic_snapshots')
    op.drop_index('ix_holistic_snapshots_user_id', table_name='holistic_snapshots')
    op.drop_table('holistic_snapshots')
    
    op.drop_index('ix_visualizations_created_at', table_name='visualizations')
    op.drop_index('ix_visualizations_goal_id', table_name='visualizations')
    op.drop_index('ix_visualizations_user_id', table_name='visualizations')
    op.drop_table('visualizations')
    
    op.drop_index('ix_agent_analyses_created_at', table_name='agent_analyses')
    op.drop_index('ix_agent_analyses_agent_type', table_name='agent_analyses')
    op.drop_index('ix_agent_analyses_goal_id', table_name='agent_analyses')
    op.drop_index('ix_agent_analyses_user_id', table_name='agent_analyses')
    op.drop_table('agent_analyses')
    
    op.drop_index('ix_goal_states_status', table_name='goal_states')
    op.drop_index('ix_goal_states_goal_id', table_name='goal_states')
    op.drop_index('ix_goal_states_user_id', table_name='goal_states')
    op.drop_table('goal_states')
    
    op.drop_index('ix_agent_sessions_phase', table_name='agent_sessions')
    op.drop_index('ix_agent_sessions_session_id', table_name='agent_sessions')
    op.drop_index('ix_agent_sessions_user_id', table_name='agent_sessions')
    op.drop_table('agent_sessions')


