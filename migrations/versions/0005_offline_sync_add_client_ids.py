"""Add client ids for offline sync idempotency

Revision ID: 0005_offline_sync
Revises: 0004_calendar_reminders
Create Date: 2026-07-06

Workout.client_uuid (unique per user) lets a replayed sync batch find the
workout it already created; ExerciseLog.client_log_id (unique) deduplicates
individual sets. NULLs (everything logged online) are unconstrained.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0005_offline_sync'
down_revision = '0004_calendar_reminders'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workout', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_uuid', sa.String(length=36), nullable=True))
        batch_op.create_unique_constraint('uq_workout_user_client', ['user_id', 'client_uuid'])

    with op.batch_alter_table('exercise_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_log_id', sa.String(length=36), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_exercise_log_client_log_id'), ['client_log_id'], unique=True
        )


def downgrade():
    with op.batch_alter_table('exercise_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exercise_log_client_log_id'))
        batch_op.drop_column('client_log_id')

    with op.batch_alter_table('workout', schema=None) as batch_op:
        batch_op.drop_constraint('uq_workout_user_client', type_='unique')
        batch_op.drop_column('client_uuid')
