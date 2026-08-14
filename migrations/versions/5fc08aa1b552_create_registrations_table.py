"""create registrations table

Revision ID: 5fc08aa1b552
Revises: ca0335d9ba1c
Create Date: 2026-08-14 20:53:54.337128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fc08aa1b552'
down_revision: Union[str, Sequence[str], None] = 'ca0335d9ba1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('registrations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('stripe_session_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('pending', 'paid', 'expired', name='registration_status'), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('whatsapp', sa.String(length=20), nullable=False),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('city', sa.String(length=255), nullable=False),
    sa.Column('institution', sa.String(length=255), nullable=False),
    sa.Column('specialty', sa.String(length=255), nullable=False),
    sa.Column('referral', sa.String(length=255), nullable=False),
    sa.Column('scct_member', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('physician_type', sa.String(length=100), nullable=True),
    sa.Column('attendance', sa.String(length=100), nullable=True),
    sa.Column('follow_up_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_registrations_course_id'), 'registrations', ['course_id'], unique=False)
    op.create_index(op.f('ix_registrations_email'), 'registrations', ['email'], unique=False)
    op.create_index(op.f('ix_registrations_stripe_session_id'), 'registrations', ['stripe_session_id'], unique=True)
    op.create_index(op.f('ix_registrations_user_id'), 'registrations', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_registrations_user_id'), table_name='registrations')
    op.drop_index(op.f('ix_registrations_stripe_session_id'), table_name='registrations')
    op.drop_index(op.f('ix_registrations_email'), table_name='registrations')
    op.drop_index(op.f('ix_registrations_course_id'), table_name='registrations')
    op.drop_table('registrations')
    # The users_role migration's downgrade doesn't drop its enum type after
    # dropping the users table (a pre-existing gap, not touched here) — fixed
    # going forward for this new type instead of repeating that gap.
    sa.Enum(name='registration_status').drop(op.get_bind(), checkfirst=True)
