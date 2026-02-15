"""Add last_scoring to game

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
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
    if not _column_exists('game', 'last_scoring'):
        op.add_column('game', sa.Column('last_scoring', sa.Text(), nullable=True))


def downgrade():
    if _column_exists('game', 'last_scoring'):
        op.drop_column('game', 'last_scoring')
