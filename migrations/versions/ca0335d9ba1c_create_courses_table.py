"""create courses table

Revision ID: ca0335d9ba1c
Revises: f3d9a4135748
Create Date: 2026-08-14 20:53:11.329362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca0335d9ba1c'
down_revision: Union[str, Sequence[str], None] = 'f3d9a4135748'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('courses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_courses_slug'), 'courses', ['slug'], unique=True)

    # Seed the fixed set of course offerings — the slug matches the
    # frontend's existing LevelId ("1" / "1.5" / "2") and Stripe checkout
    # metadata exactly, so no remapping is needed anywhere else.
    courses_table = sa.table(
        'courses',
        sa.column('id', sa.UUID()),
        sa.column('slug', sa.String()),
        sa.column('title', sa.String()),
        sa.column('price_cents', sa.Integer()),
        sa.column('currency', sa.String()),
        sa.column('is_active', sa.Boolean()),
        sa.column('sort_order', sa.Integer()),
    )
    op.bulk_insert(courses_table, [
        {
            'id': '2d3e6f8a-1b1c-4b7e-9b1a-000000000001',
            'slug': '1',
            'title': 'Cardiac CT Level I',
            'price_cents': 25000,
            'currency': 'usd',
            'is_active': True,
            'sort_order': 0,
        },
        {
            'id': '2d3e6f8a-1b1c-4b7e-9b1a-000000000002',
            'slug': '1.5',
            'title': 'Cardiac CT 1.5: A PCI Planning Course',
            'price_cents': 30000,
            'currency': 'usd',
            'is_active': True,
            'sort_order': 1,
        },
        {
            'id': '2d3e6f8a-1b1c-4b7e-9b1a-000000000003',
            'slug': '2',
            'title': 'Hybrid Advance Cardiac CT Course (Level II)',
            'price_cents': 190000,
            'currency': 'usd',
            'is_active': True,
            'sort_order': 2,
        },
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_courses_slug'), table_name='courses')
    op.drop_table('courses')
