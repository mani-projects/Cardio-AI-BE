"""add coupon code to registrations

Revision ID: 90741e6dbac5
Revises: bd1473472fb0
Create Date: 2026-08-23 01:04:45.978309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90741e6dbac5'
down_revision: Union[str, Sequence[str], None] = 'bd1473472fb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('registrations', sa.Column('coupon_code', sa.String(255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('registrations', 'coupon_code')
