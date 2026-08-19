"""add case categories table

Revision ID: cd402174f37f
Revises: 6629c4fec45a
Create Date: 2026-08-19 21:00:50.233997

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd402174f37f'
down_revision: Union[str, Sequence[str], None] = '6629c4fec45a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('case_categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_categories_course_id'), 'case_categories', ['course_id'], unique=False)
    op.create_index('ix_case_categories_course_id_name', 'case_categories', ['course_id', 'name'], unique=True)

    categories_table = sa.table(
        'case_categories',
        sa.column('id', sa.UUID()),
        sa.column('course_id', sa.UUID()),
        sa.column('name', sa.String()),
        sa.column('is_active', sa.Boolean()),
        sa.column('sort_order', sa.Integer()),
    )
    course_ids = [
        '2d3e6f8a-1b1c-4b7e-9b1a-000000000001',
        '2d3e6f8a-1b1c-4b7e-9b1a-000000000002',
        '2d3e6f8a-1b1c-4b7e-9b1a-000000000003',
    ]
    category_names = ['CAD', 'Plaque', 'CT-Cath', 'Structural-Aortic']
    seed_rows = [
        {
            'id': str(uuid.uuid4()),
            'course_id': course_id,
            'name': name,
            'is_active': True,
            'sort_order': sort_order,
        }
        for course_id in course_ids
        for sort_order, name in enumerate(category_names)
    ]
    op.bulk_insert(categories_table, seed_rows)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_case_categories_course_id_name', table_name='case_categories')
    op.drop_index(op.f('ix_case_categories_course_id'), table_name='case_categories')
    op.drop_table('case_categories')
