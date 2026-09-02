"""Add ruleset_vote column to user table

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-02 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('ruleset_vote', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('user', 'ruleset_vote')
