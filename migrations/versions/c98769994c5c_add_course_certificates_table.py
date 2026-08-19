"""add course certificates table

Revision ID: c98769994c5c
Revises: 3392963b4b0b
Create Date: 2026-08-19 22:41:23.319083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c98769994c5c'
down_revision: Union[str, Sequence[str], None] = '3392963b4b0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('course_certificates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('file_key', sa.String(length=1024), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_course_certificates_course_id'), 'course_certificates', ['course_id'], unique=True)
    op.create_index(op.f('ix_course_certificates_uploaded_by'), 'course_certificates', ['uploaded_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_course_certificates_uploaded_by'), table_name='course_certificates')
    op.drop_index(op.f('ix_course_certificates_course_id'), table_name='course_certificates')
    op.drop_table('course_certificates')
