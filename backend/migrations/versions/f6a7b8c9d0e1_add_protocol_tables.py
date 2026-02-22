"""Add protocol tables (Person, GameLog, GameLogPlayer, NickMapping)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def _table_exists(table):
    conn = op.get_bind()
    try:
        result = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :tbl"
        ), {"tbl": table})
        return result.fetchone() is not None
    except Exception:
        return False


def upgrade():
    if not _table_exists('person'):
        op.create_table('person',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )

    if not _table_exists('game_log'):
        op.create_table('game_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('game_uuid', sa.String(length=200), nullable=True),
            sa.Column('game_date', sa.Date(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('mapping_complete', sa.Boolean(), nullable=True,
                       server_default=sa.text('0')),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_game_log_game_uuid', 'game_log', ['game_uuid'])
        op.create_index('ix_game_log_game_date', 'game_log', ['game_date'])

    if not _table_exists('game_log_player'):
        op.create_table('game_log_player',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('game_log_id', sa.Integer(), nullable=False),
            sa.Column('nick', sa.String(length=200), nullable=False),
            sa.Column('is_loser', sa.Boolean(), nullable=True,
                       server_default=sa.text('0')),
            sa.Column('person_id', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['game_log_id'], ['game_log.id']),
            sa.ForeignKeyConstraint(['person_id'], ['person.id'])
        )

    if not _table_exists('nick_mapping'):
        op.create_table('nick_mapping',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nick', sa.String(length=200), nullable=False),
            sa.Column('person_id', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('nick'),
            sa.ForeignKeyConstraint(['person_id'], ['person.id'])
        )
        op.create_index('ix_nick_mapping_nick', 'nick_mapping', ['nick'])


def downgrade():
    if _table_exists('nick_mapping'):
        op.drop_table('nick_mapping')
    if _table_exists('game_log_player'):
        op.drop_table('game_log_player')
    if _table_exists('game_log'):
        op.drop_table('game_log')
    if _table_exists('person'):
        op.drop_table('person')
