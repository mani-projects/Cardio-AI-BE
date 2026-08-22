"""add amount paid and discount percent to registrations

Revision ID: 05344cbe2e70
Revises: 90741e6dbac5
Create Date: 2026-08-23 01:59:03.188384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05344cbe2e70'
down_revision: Union[str, Sequence[str], None] = '90741e6dbac5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('registrations', sa.Column('amount_paid_cents', sa.Integer(), nullable=True))
    op.add_column('registrations', sa.Column('discount_percent', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('registrations', 'discount_percent')
    op.drop_column('registrations', 'amount_paid_cents')
