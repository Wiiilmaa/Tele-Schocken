"""Add keyboard_bindings to person

Revision ID: c0d1e2f3a4b5
Revises: a7b8c9d0e1f2
Create Date: 2026-03-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c0d1e2f3a4b5'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keyboard_bindings', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.drop_column('keyboard_bindings')
