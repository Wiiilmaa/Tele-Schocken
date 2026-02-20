"""Add unique constraint on user (name, game_id)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _index_exists(table, index_name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SHOW INDEX FROM `{table}` WHERE Key_name = :idx"
    ), {"idx": index_name})
    return result.fetchone() is not None


def upgrade():
    if not _index_exists('user', 'uq_user_name_game'):
        op.create_index('uq_user_name_game', 'user', ['name', 'game_id'], unique=True)


def downgrade():
    if _index_exists('user', 'uq_user_name_game'):
        op.drop_index('uq_user_name_game', table_name='user')
