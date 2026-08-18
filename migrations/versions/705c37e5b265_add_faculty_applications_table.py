"""add faculty applications table

Revision ID: 705c37e5b265
Revises: b2fa91d99b8d
Create Date: 2026-08-18 20:50:36.144751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '705c37e5b265'
down_revision: Union[str, Sequence[str], None] = 'b2fa91d99b8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('faculty_applications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('specialty', sa.String(length=255), nullable=False),
    sa.Column('institution', sa.String(length=255), nullable=False),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('years_experience', sa.Integer(), nullable=False),
    sa.Column('credentials_note', sa.Text(), nullable=False),
    sa.Column('credential_file_url', sa.String(length=1024), nullable=True),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', name='faculty_application_status'), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_faculty_applications_created_user_id'), 'faculty_applications', ['created_user_id'], unique=False)
    op.create_index(op.f('ix_faculty_applications_email'), 'faculty_applications', ['email'], unique=False)
    op.create_index(op.f('ix_faculty_applications_reviewed_by'), 'faculty_applications', ['reviewed_by'], unique=False)
    op.create_index(op.f('ix_faculty_applications_status'), 'faculty_applications', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_faculty_applications_status'), table_name='faculty_applications')
    op.drop_index(op.f('ix_faculty_applications_reviewed_by'), table_name='faculty_applications')
    op.drop_index(op.f('ix_faculty_applications_email'), table_name='faculty_applications')
    op.drop_index(op.f('ix_faculty_applications_created_user_id'), table_name='faculty_applications')
    op.drop_table('faculty_applications')
    sa.Enum(name='faculty_application_status').drop(op.get_bind(), checkfirst=True)
