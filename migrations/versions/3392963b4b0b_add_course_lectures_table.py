"""add course lectures table

Revision ID: 3392963b4b0b
Revises: 60cd54e6100b
Create Date: 2026-08-19 22:26:12.928810

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3392963b4b0b'
down_revision: Union[str, Sequence[str], None] = '60cd54e6100b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('course_lectures',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('source', sa.Enum('link', 'upload', name='lecture_source'), nullable=False),
    sa.Column('video_url', sa.String(length=1024), nullable=True),
    sa.Column('file_key', sa.String(length=1024), nullable=True),
    sa.Column('group_label', sa.String(length=255), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_course_lectures_course_id'), 'course_lectures', ['course_id'], unique=False)
    op.create_index(op.f('ix_course_lectures_created_by'), 'course_lectures', ['created_by'], unique=False)

    op.create_table('lecture_watch_state',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('lecture_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('watched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['lecture_id'], ['course_lectures.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lecture_watch_state_lecture_id'), 'lecture_watch_state', ['lecture_id'], unique=False)
    op.create_index(op.f('ix_lecture_watch_state_user_id'), 'lecture_watch_state', ['user_id'], unique=False)
    op.create_index(
        'ix_lecture_watch_state_lecture_id_user_id', 'lecture_watch_state', ['lecture_id', 'user_id'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_lecture_watch_state_lecture_id_user_id', table_name='lecture_watch_state')
    op.drop_index(op.f('ix_lecture_watch_state_user_id'), table_name='lecture_watch_state')
    op.drop_index(op.f('ix_lecture_watch_state_lecture_id'), table_name='lecture_watch_state')
    op.drop_table('lecture_watch_state')

    op.drop_index(op.f('ix_course_lectures_created_by'), table_name='course_lectures')
    op.drop_index(op.f('ix_course_lectures_course_id'), table_name='course_lectures')
    op.drop_table('course_lectures')
    sa.Enum(name='lecture_source').drop(op.get_bind(), checkfirst=True)
