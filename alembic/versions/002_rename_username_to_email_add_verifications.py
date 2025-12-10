"""Rename username to email in users table and add verifications table

Revision ID: 002
Revises: 001
Create Date: 2024-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename username column to email in users table
    op.drop_index('ix_users_username', table_name='users')
    op.alter_column('users', 'username', new_column_name='email')
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Create verifications table
    op.create_table(
        'verifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('otp', sa.String(length=6), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_verifications_token'), 'verifications', ['token'], unique=True)
    op.create_index(op.f('ix_verifications_email'), 'verifications', ['email'], unique=True)


def downgrade() -> None:
    # Drop verifications table
    op.drop_index(op.f('ix_verifications_email'), table_name='verifications')
    op.drop_index(op.f('ix_verifications_token'), table_name='verifications')
    op.drop_table('verifications')

    # Rename email column back to username in users table
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.alter_column('users', 'email', new_column_name='username')
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
