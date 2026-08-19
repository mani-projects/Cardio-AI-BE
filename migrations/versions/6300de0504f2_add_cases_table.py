"""add cases table

Revision ID: 6300de0504f2
Revises: cd402174f37f
Create Date: 2026-08-19 21:15:36.186647

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6300de0504f2'
down_revision: Union[str, Sequence[str], None] = 'cd402174f37f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('cases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('faculty_id', sa.UUID(), nullable=True),
    sa.Column('case_number', sa.String(length=100), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('report_text', sa.Text(), nullable=False),
    sa.Column('answer_key_findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('imaging_reference', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Enum('pending_review', 'approved', 'rejected', name='case_status'), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['case_categories.id'], ),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['faculty_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_number')
    )
    op.create_index(op.f('ix_cases_course_id'), 'cases', ['course_id'], unique=False)
    op.create_index(op.f('ix_cases_category_id'), 'cases', ['category_id'], unique=False)
    op.create_index(op.f('ix_cases_faculty_id'), 'cases', ['faculty_id'], unique=False)
    op.create_index(op.f('ix_cases_reviewed_by'), 'cases', ['reviewed_by'], unique=False)
    op.create_index(op.f('ix_cases_status'), 'cases', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_cases_status'), table_name='cases')
    op.drop_index(op.f('ix_cases_reviewed_by'), table_name='cases')
    op.drop_index(op.f('ix_cases_faculty_id'), table_name='cases')
    op.drop_index(op.f('ix_cases_category_id'), table_name='cases')
    op.drop_index(op.f('ix_cases_course_id'), table_name='cases')
    op.drop_table('cases')
    sa.Enum(name='case_status').drop(op.get_bind(), checkfirst=True)
