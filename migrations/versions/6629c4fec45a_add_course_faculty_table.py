"""add course faculty table

Revision ID: 6629c4fec45a
Revises: 705c37e5b265
Create Date: 2026-08-19 19:47:38.715010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6629c4fec45a'
down_revision: Union[str, Sequence[str], None] = '705c37e5b265'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('course_faculty',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('assigned_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_course_faculty_assigned_by'), 'course_faculty', ['assigned_by'], unique=False)
    op.create_index(op.f('ix_course_faculty_course_id'), 'course_faculty', ['course_id'], unique=False)
    op.create_index('ix_course_faculty_course_id_user_id', 'course_faculty', ['course_id', 'user_id'], unique=True)
    op.create_index(op.f('ix_course_faculty_user_id'), 'course_faculty', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_course_faculty_user_id'), table_name='course_faculty')
    op.drop_index('ix_course_faculty_course_id_user_id', table_name='course_faculty')
    op.drop_index(op.f('ix_course_faculty_course_id'), table_name='course_faculty')
    op.drop_index(op.f('ix_course_faculty_assigned_by'), table_name='course_faculty')
    op.drop_table('course_faculty')
