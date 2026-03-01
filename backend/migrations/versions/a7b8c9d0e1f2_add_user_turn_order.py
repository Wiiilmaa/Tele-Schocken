"""Add turn_order to user for correct rotation ordering

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-02-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    """Check whether a column already exists (idempotent migrations)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SHOW COLUMNS FROM `{table}` LIKE :col"
    ), {"col": column})
    return result.fetchone() is not None


def upgrade():
    if not _column_exists('user', 'turn_order'):
        op.add_column('user', sa.Column('turn_order', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    if _column_exists('user', 'turn_order'):
        op.drop_column('user', 'turn_order')
