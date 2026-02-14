"""Add multi-admin, rulesets, deferred actions, mid-game joining, reveal votes

Revision ID: a1b2c3d4e5f6
Revises: 2c71994ad95b
Create Date: 2026-02-14 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2c71994ad95b'
branch_labels = None
depends_on = None


def upgrade():
    # User table: add is_admin, leave_after_game, pending_join
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_admin', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('leave_after_game', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('pending_join', sa.Boolean(), nullable=True, server_default='0'))

    # Game table: add lobby_after_game, reveal_votes, ruleset_id
    with op.batch_alter_table('game', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lobby_after_game', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('reveal_votes', sa.Text(), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('ruleset_id', sa.String(length=50), nullable=True))

    # Data migration: set is_admin=True for users matching their game's admin_user_id
    # This works for both SQLite and MySQL
    op.execute(
        "UPDATE user SET is_admin = 1 WHERE id IN "
        "(SELECT admin_user_id FROM game WHERE admin_user_id IS NOT NULL)"
    )

    # Set default ruleset for existing games
    op.execute(
        "UPDATE game SET ruleset_id = 'classic_13' WHERE ruleset_id IS NULL"
    )


def downgrade():
    with op.batch_alter_table('game', schema=None) as batch_op:
        batch_op.drop_column('ruleset_id')
        batch_op.drop_column('reveal_votes')
        batch_op.drop_column('lobby_after_game')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('pending_join')
        batch_op.drop_column('leave_after_game')
        batch_op.drop_column('is_admin')
