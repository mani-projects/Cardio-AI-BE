"""add free status to registrations

Revision ID: b2fa91d99b8d
Revises: ea29f8aa4e82
Create Date: 2026-08-18 19:41:47.738831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2fa91d99b8d'
down_revision: Union[str, Sequence[str], None] = 'ea29f8aa4e82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Lets an admin free-register a learner into a course (no Stripe session)
    # without repurposing "paid" for something that isn't a real payment.
    op.execute("ALTER TYPE registration_status ADD VALUE IF NOT EXISTS 'free'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres can't drop a single enum value without recreating the whole
    # type; not exercised by this project's deploy flow (only `upgrade head`
    # ever runs in practice).
    pass
