"""Add penalty_count to user

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
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
    if not _column_exists('user', 'penalty_count'):
        op.add_column('user', sa.Column('penalty_count', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    if _column_exists('user', 'penalty_count'):
        op.drop_column('user', 'penalty_count')
