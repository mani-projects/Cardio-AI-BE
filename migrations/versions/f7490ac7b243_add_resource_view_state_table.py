"""add resource view state table

Revision ID: f7490ac7b243
Revises: c98769994c5c
Create Date: 2026-08-20 18:18:09.818070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7490ac7b243'
down_revision: Union[str, Sequence[str], None] = 'c98769994c5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('resource_view_state',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['resource_id'], ['course_resources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resource_view_state_resource_id'), 'resource_view_state', ['resource_id'], unique=False)
    op.create_index(op.f('ix_resource_view_state_user_id'), 'resource_view_state', ['user_id'], unique=False)
    op.create_index(
        'ix_resource_view_state_resource_id_user_id', 'resource_view_state', ['resource_id', 'user_id'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_resource_view_state_resource_id_user_id', table_name='resource_view_state')
    op.drop_index(op.f('ix_resource_view_state_user_id'), table_name='resource_view_state')
    op.drop_index(op.f('ix_resource_view_state_resource_id'), table_name='resource_view_state')
    op.drop_table('resource_view_state')
