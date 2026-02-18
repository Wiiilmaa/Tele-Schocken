"""Remove global unique constraint on user.name

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def _index_exists(table, index_name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SHOW INDEX FROM `{table}` WHERE Key_name = :idx"
    ), {"idx": index_name})
    return result.fetchone() is not None


def upgrade():
    if _index_exists('user', 'ix_user_name'):
        op.drop_index('ix_user_name', table_name='user')
        op.create_index('ix_user_name', 'user', ['name'], unique=False)


def downgrade():
    if _index_exists('user', 'ix_user_name'):
        op.drop_index('ix_user_name', table_name='user')
        op.create_index('ix_user_name', 'user', ['name'], unique=True)
