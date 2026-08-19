"""add course resources table

Revision ID: 60cd54e6100b
Revises: 7a8710c558b0
Create Date: 2026-08-19 21:32:10.318470

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60cd54e6100b'
down_revision: Union[str, Sequence[str], None] = '7a8710c558b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('course_resources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('category', sa.Enum('guidelines', 'templates', 'documents', name='resource_category'), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('subtitle', sa.String(length=255), nullable=True),
    sa.Column('file_key', sa.String(length=1024), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('file_size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_course_resources_course_id'), 'course_resources', ['course_id'], unique=False)
    op.create_index(op.f('ix_course_resources_category'), 'course_resources', ['category'], unique=False)
    op.create_index(op.f('ix_course_resources_uploaded_by'), 'course_resources', ['uploaded_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_course_resources_uploaded_by'), table_name='course_resources')
    op.drop_index(op.f('ix_course_resources_category'), table_name='course_resources')
    op.drop_index(op.f('ix_course_resources_course_id'), table_name='course_resources')
    op.drop_table('course_resources')
    sa.Enum(name='resource_category').drop(op.get_bind(), checkfirst=True)
