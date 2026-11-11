"""registration channel + webhook reply action columns

Revision ID: b7d21e4a9c30
Revises: a489a7b88ae5
Create Date: 2026-11-10 09:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d21e4a9c30'
down_revision: Union[str, None] = 'a489a7b88ae5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Part 3: registration records the patient's preferred reminder channel.
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('preferred_channel', sa.String(length=16), nullable=False, server_default='whatsapp')
        )

    # Part 3: inbound WhatsApp/Twilio replies are recorded on the occurrence
    # (the status vocabulary itself is deliberately unchanged).
    with op.batch_alter_table('reminder_occurrences', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('patient_action', sa.String(length=16), nullable=False, server_default='')
        )
        batch_op.add_column(sa.Column('patient_action_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reminder_occurrences', schema=None) as batch_op:
        batch_op.drop_column('patient_action_at')
        batch_op.drop_column('patient_action')

    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_column('preferred_channel')
