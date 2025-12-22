"""add_user_kms_mapping_columns

Revision ID: 006
Revises: 005
Create Date: 2025-12-17

Adds missing columns to existing user_kms_mapping table:
- kms_key_id
- alias
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add kms_key_id column (extract from ARN for quick lookups)
    op.add_column('user_kms_mapping', sa.Column(
        'kms_key_id',
        sa.String(length=64),
        nullable=True,
        comment='AWS KMS Key ID (UUID format)'
    ))

    # Add alias column
    op.add_column('user_kms_mapping', sa.Column(
        'alias',
        sa.String(length=256),
        nullable=True,
        comment='KMS key alias (e.g., alias/vecta-user-123)'
    ))


def downgrade() -> None:
    op.drop_column('user_kms_mapping', 'alias')
    op.drop_column('user_kms_mapping', 'kms_key_id')
