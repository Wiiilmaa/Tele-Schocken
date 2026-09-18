"""Add ruleset_vote to person (remembered vote of a known player)

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-09-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'h8c9d0e1f2a3'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ruleset_vote', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.drop_column('ruleset_vote')
