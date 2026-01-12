"""add_persona_and_life_aspiration_fields

Revision ID: 007
Revises: 006
Create Date: 2026-01-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Persona fields (Phase 1 discovery)
    op.add_column('users', sa.Column('age', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('relationship_status', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('has_kids', sa.Boolean(), nullable=True))
    op.add_column('users', sa.Column('number_of_kids', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('career', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(255), nullable=True))

    # Life aspirations (Phase 2 discovery)
    op.add_column('users', sa.Column('marriage_plans', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('family_plans', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('career_goals', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('retirement_age', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('retirement_vision', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('lifestyle_goals', sa.String(500), nullable=True))


def downgrade() -> None:
    # Remove life aspiration fields
    op.drop_column('users', 'lifestyle_goals')
    op.drop_column('users', 'retirement_vision')
    op.drop_column('users', 'retirement_age')
    op.drop_column('users', 'career_goals')
    op.drop_column('users', 'family_plans')
    op.drop_column('users', 'marriage_plans')

    # Remove persona fields
    op.drop_column('users', 'location')
    op.drop_column('users', 'career')
    op.drop_column('users', 'number_of_kids')
    op.drop_column('users', 'has_kids')
    op.drop_column('users', 'relationship_status')
    op.drop_column('users', 'age')
