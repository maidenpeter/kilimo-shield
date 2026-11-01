"""Phase 3 review fix: a photo app sign-in version, so a PIN reset or "turn off" signs every phone out.

Revision ID: 0004a
Revises: 0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0004a'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.drop_column('session_version')
