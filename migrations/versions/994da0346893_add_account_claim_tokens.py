"""add account claim tokens

Revision ID: 994da0346893
Revises: 5fc08aa1b552
Create Date: 2026-08-14 20:54:19.117154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '994da0346893'
down_revision: Union[str, Sequence[str], None] = '5fc08aa1b552'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A payment-only, pre-provisioned account (created when someone pays for
    # a course with no existing CardioAI account) has no password yet.
    op.alter_column('users', 'hashed_password',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)

    op.create_table('account_claim_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=255), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_account_claim_tokens_token_hash'), 'account_claim_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_account_claim_tokens_user_id'), 'account_claim_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_account_claim_tokens_user_id'), table_name='account_claim_tokens')
    op.drop_index(op.f('ix_account_claim_tokens_token_hash'), table_name='account_claim_tokens')
    op.drop_table('account_claim_tokens')

    # NOTE: a real downgrade here would need to backfill any NULLs (e.g. any
    # still-unclaimed pre-provisioned accounts) before this can succeed —
    # not exercised by this project's deploy flow (only `upgrade head` ever
    # runs in practice), but worth knowing before ever running it for real.
    op.alter_column('users', 'hashed_password',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
