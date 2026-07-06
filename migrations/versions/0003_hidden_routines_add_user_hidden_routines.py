"""Add user.hidden_routines for per-user routine visibility

Revision ID: 0003_hidden_routines
Revises: 0002_indexes
Create Date: 2026-07-06

Existing rows get NULL, which the model treats the same as '' (nothing hidden).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0003_hidden_routines'
down_revision = '0002_indexes'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hidden_routines', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('hidden_routines')
