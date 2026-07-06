"""Add calendar-feed token and reminder preferences to user

Revision ID: 0004_calendar_reminders
Revises: 0003_hidden_routines
Create Date: 2026-07-06

Existing rows get NULLs, which the app treats as: feed disabled, reminders
off, 07:00 local, UTC.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0004_calendar_reminders'
down_revision = '0003_hidden_routines'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ics_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reminder_enabled', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('reminder_time', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('tz_offset_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_reminded_on', sa.Date(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_ics_token'), ['ics_token'], unique=True)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_ics_token'))
        batch_op.drop_column('last_reminded_on')
        batch_op.drop_column('tz_offset_minutes')
        batch_op.drop_column('reminder_time')
        batch_op.drop_column('reminder_enabled')
        batch_op.drop_column('ics_token')
