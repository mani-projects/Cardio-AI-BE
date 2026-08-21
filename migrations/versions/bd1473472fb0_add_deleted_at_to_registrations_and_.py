"""add deleted_at to registrations and users

Revision ID: bd1473472fb0
Revises: f7490ac7b243
Create Date: 2026-08-21 21:18:01.636062

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd1473472fb0'
down_revision: Union[str, Sequence[str], None] = 'f7490ac7b243'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, no server_default: NULL means "not deleted" a soft-delete
    # sets this to the deletion time, and a background purge job hard-deletes
    # rows once it's more than 3 days old. See registrations/users service.py.
    op.add_column('registrations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'deleted_at')
    op.drop_column('registrations', 'deleted_at')
