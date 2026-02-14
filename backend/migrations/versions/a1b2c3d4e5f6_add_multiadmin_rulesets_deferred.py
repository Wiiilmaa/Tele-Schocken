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


def _column_exists(table, column):
    """Check whether a column already exists (idempotent migrations)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SHOW COLUMNS FROM `{table}` LIKE :col"
    ), {"col": column})
    return result.fetchone() is not None


def upgrade():
    # User table: add is_admin, leave_after_game, pending_join
    if not _column_exists('user', 'is_admin'):
        op.add_column('user', sa.Column('is_admin', sa.Boolean(), nullable=True, server_default=sa.text('0')))
    if not _column_exists('user', 'leave_after_game'):
        op.add_column('user', sa.Column('leave_after_game', sa.Boolean(), nullable=True, server_default=sa.text('0')))
    if not _column_exists('user', 'pending_join'):
        op.add_column('user', sa.Column('pending_join', sa.Boolean(), nullable=True, server_default=sa.text('0')))

    # Game table: add lobby_after_game, reveal_votes, ruleset_id
    if not _column_exists('game', 'lobby_after_game'):
        op.add_column('game', sa.Column('lobby_after_game', sa.Boolean(), nullable=True, server_default=sa.text('0')))
    if not _column_exists('game', 'reveal_votes'):
        op.add_column('game', sa.Column('reveal_votes', sa.Text(), nullable=True))
    if not _column_exists('game', 'ruleset_id'):
        op.add_column('game', sa.Column('ruleset_id', sa.String(length=50), nullable=True))

    # Data migration: set is_admin=True for users matching their game's admin_user_id
    if _column_exists('game', 'admin_user_id'):
        op.execute(
            "UPDATE user SET is_admin = 1 WHERE id IN "
            "(SELECT admin_user_id FROM game WHERE admin_user_id IS NOT NULL)"
        )

    # Set default ruleset for existing games
    op.execute(
        "UPDATE game SET ruleset_id = 'classic_13' WHERE ruleset_id IS NULL"
    )

    # Fix the MySQL ENUM column: SQLAlchemy 2.0 uses enum NAMES (uppercase)
    # for db.Enum(PEP435Enum) without values_callable. The original migration
    # had NAMES but was missing PLAYFINAL. A previous version of this migration
    # may have converted to lowercase values, so we handle both directions.
    #
    # Step 1: Expand ENUM to include both lowercase values AND uppercase names
    #         for the mismatched pairs (roundfinish≠ROUNDFINISCH, gamefinish≠GAMEFINISCH).
    #         WAITING/STARTED/PLAYFINAL are handled by case-insensitive rename.
    op.execute(
        "ALTER TABLE game MODIFY COLUMN status "
        "ENUM('WAITING','STARTED','ROUNDFINISCH','PLAYFINAL','GAMEFINISCH',"
        "'roundfinish','gamefinish') NULL"
    )
    # Step 2: Convert any lowercase values to uppercase NAMES
    op.execute(
        "UPDATE game SET status = 'ROUNDFINISCH' WHERE status = 'roundfinish'"
    )
    op.execute(
        "UPDATE game SET status = 'GAMEFINISCH' WHERE status = 'gamefinish'"
    )
    # Step 3: Shrink ENUM to final uppercase NAMES only
    op.execute(
        "ALTER TABLE game MODIFY COLUMN status "
        "ENUM('WAITING','STARTED','ROUNDFINISCH','PLAYFINAL','GAMEFINISCH') NULL"
    )


def downgrade():
    if _column_exists('game', 'ruleset_id'):
        op.drop_column('game', 'ruleset_id')
    if _column_exists('game', 'reveal_votes'):
        op.drop_column('game', 'reveal_votes')
    if _column_exists('game', 'lobby_after_game'):
        op.drop_column('game', 'lobby_after_game')

    if _column_exists('user', 'pending_join'):
        op.drop_column('user', 'pending_join')
    if _column_exists('user', 'leave_after_game'):
        op.drop_column('user', 'leave_after_game')
    if _column_exists('user', 'is_admin'):
        op.drop_column('user', 'is_admin')
