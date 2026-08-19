"""add case attempts and case feedback tables

Revision ID: 7a8710c558b0
Revises: 6300de0504f2
Create Date: 2026-08-19 21:24:55.309984

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7a8710c558b0'
down_revision: Union[str, Sequence[str], None] = '6300de0504f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('case_attempts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('learner_id', sa.UUID(), nullable=True),
    sa.Column('mode', sa.Enum('findings', 'structured_report', name='case_attempt_mode'), nullable=False),
    sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('technique_text', sa.Text(), nullable=True),
    sa.Column('cadrads_lm', sa.String(length=10), nullable=True),
    sa.Column('cadrads_lad', sa.String(length=10), nullable=True),
    sa.Column('cadrads_lcx', sa.String(length=10), nullable=True),
    sa.Column('cadrads_rca', sa.String(length=10), nullable=True),
    sa.Column('plaque_text', sa.Text(), nullable=True),
    sa.Column('impression_text', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('in_progress', 'submitted', 'reviewed', name='case_attempt_status'), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['learner_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_attempts_case_id'), 'case_attempts', ['case_id'], unique=False)
    op.create_index(op.f('ix_case_attempts_learner_id'), 'case_attempts', ['learner_id'], unique=False)
    op.create_index(op.f('ix_case_attempts_status'), 'case_attempts', ['status'], unique=False)
    op.create_index('ix_case_attempts_case_id_learner_id', 'case_attempts', ['case_id', 'learner_id'], unique=True)

    op.create_table('case_feedback',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('attempt_id', sa.UUID(), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('diagnosis_summary', sa.Text(), nullable=False),
    sa.Column('score_summary', sa.Text(), nullable=False),
    sa.Column('comments', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['case_attempts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('attempt_id')
    )
    op.create_index(op.f('ix_case_feedback_reviewed_by'), 'case_feedback', ['reviewed_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_case_feedback_reviewed_by'), table_name='case_feedback')
    op.drop_table('case_feedback')

    op.drop_index('ix_case_attempts_case_id_learner_id', table_name='case_attempts')
    op.drop_index(op.f('ix_case_attempts_status'), table_name='case_attempts')
    op.drop_index(op.f('ix_case_attempts_learner_id'), table_name='case_attempts')
    op.drop_index(op.f('ix_case_attempts_case_id'), table_name='case_attempts')
    op.drop_table('case_attempts')
    sa.Enum(name='case_attempt_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='case_attempt_mode').drop(op.get_bind(), checkfirst=True)
