"""Phase 1 (remaining brief): M-Pesa re-check, refunds paid, insurer premium paybill, advisory scope.

M-Pesa requests still pending when this runs are queued for a status check straight away, so none is
dropped. Existing weather advisories become "every SACCO" (sacco_id NULL), so AgroShield operations now
approve or withdraw them.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('refund',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=False),
    sa.Column('amount_kes', sa.Float(), nullable=False),
    sa.Column('paid_on', sa.Date(), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('reference', sa.String(length=40), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('recorded_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    with op.batch_alter_table('refund', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_refund_policy_id'), ['policy_id'], unique=False)

    with op.batch_alter_table('insurer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('premium_paybill', sa.String(length=60), nullable=True))

    with op.batch_alter_table('mpesa_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('query_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('next_query_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_query_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_query_result', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('callback_amount_kes', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('callback_receipt', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('callback_txn_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('resolution', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('resolved_by', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('resolution_note', sa.String(length=300), nullable=True))
        batch_op.create_index(batch_op.f('ix_mpesa_request_next_query_at'), ['next_query_at'], unique=False)
    op.execute("UPDATE mpesa_request SET next_query_at = CURRENT_TIMESTAMP WHERE status = 'pending'")

    with op.batch_alter_table('weather_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sacco_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_weather_item_sacco_id'), ['sacco_id'], unique=False)
        batch_op.create_foreign_key('fk_weather_item_sacco_id_sacco', 'sacco', ['sacco_id'], ['id'])



def downgrade() -> None:
    with op.batch_alter_table('weather_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_weather_item_sacco_id_sacco', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_weather_item_sacco_id'))
        batch_op.drop_column('sacco_id')

    with op.batch_alter_table('mpesa_request', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mpesa_request_next_query_at'))
        batch_op.drop_column('resolution_note')
        batch_op.drop_column('resolved_by')
        batch_op.drop_column('resolution')
        batch_op.drop_column('callback_txn_at')
        batch_op.drop_column('callback_receipt')
        batch_op.drop_column('callback_amount_kes')
        batch_op.drop_column('last_query_result')
        batch_op.drop_column('last_query_at')
        batch_op.drop_column('next_query_at')
        batch_op.drop_column('query_attempts')

    with op.batch_alter_table('insurer', schema=None) as batch_op:
        batch_op.drop_column('premium_paybill')

    with op.batch_alter_table('refund', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refund_policy_id'))

    op.drop_table('refund')
