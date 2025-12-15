"""add_oauth_provider_field

Revision ID: 28c66fffae82
Revises: 004
Create Date: 2025-12-15 15:41:22.173981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add oauth_provider column
    op.add_column('users', sa.Column('oauth_provider', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_users_oauth_provider'), 'users', ['oauth_provider'], unique=False)
    
    # Make hashed_password nullable for OAuth users
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=True)


def downgrade() -> None:
    # Revert hashed_password to non-nullable
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=False)
    
    # Remove oauth_provider column
    op.drop_index(op.f('ix_users_oauth_provider'), table_name='users')
    op.drop_column('users', 'oauth_provider')
