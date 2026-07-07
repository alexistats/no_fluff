"""Add user.shared_key_unlocked_at for the shared-AI access code

Revision ID: 0006_shared_key_lock
Revises: 0005_offline_sync
Create Date: 2026-07-06

NULL = locked (when SHARED_KEY_ACCESS_CODE is configured); with no code
configured the column is ignored and the shared key stays open to everyone.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0006_shared_key_lock'
down_revision = '0005_offline_sync'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('shared_key_unlocked_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('shared_key_unlocked_at')
