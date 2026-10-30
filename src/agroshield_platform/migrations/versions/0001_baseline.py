"""Baseline: the portal schema as of 30 October 2026 (commit b35d99f, before the remaining brief).

Databases created before migrations existed (by create_all) are stamped at this revision on first start,
after a check that their tables and columns match it (agroshield_platform.migrate).

Revision ID: 0001
Revises: 
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=60), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=40), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_event_at'), ['at'], unique=False)

    op.create_table('insurer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('kiamis_record',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('national_id_hash', sa.String(length=64), nullable=False),
    sa.Column('registered_acreage', sa.Float(), nullable=True),
    sa.Column('certified_seed_purchased', sa.Boolean(), nullable=False),
    sa.Column('subsidy_eligible', sa.Boolean(), nullable=True),
    sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_sha256', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('national_id_hash')
    )
    op.create_table('public_enquiry',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name_enc', sa.Text(), nullable=False),
    sa.Column('email_enc', sa.Text(), nullable=False),
    sa.Column('email_masked', sa.String(length=80), nullable=False),
    sa.Column('phone_enc', sa.Text(), nullable=True),
    sa.Column('phone_masked', sa.String(length=24), nullable=True),
    sa.Column('organisation', sa.String(length=120), nullable=True),
    sa.Column('org_type', sa.String(length=20), nullable=False),
    sa.Column('county', sa.String(length=40), nullable=True),
    sa.Column('message', sa.String(length=1000), nullable=True),
    sa.Column('consent_text', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    op.create_table('ward_status',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('season', sa.String(length=4), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('data_through', sa.Date(), nullable=True),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('phase', sa.String(length=20), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('projected_wrsi', sa.Float(), nullable=True),
    sa.Column('projected_share', sa.Float(), nullable=False),
    sa.Column('index_version', sa.String(length=20), nullable=False),
    sa.Column('inputs_sha256', sa.String(length=64), nullable=True),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ward_status', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ward_status_ward_id'), ['ward_id'], unique=False)

    op.create_table('weather_fetch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('url', sa.String(length=400), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('detail', sa.String(length=300), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('weather_fetch', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_weather_fetch_source'), ['source'], unique=False)

    op.create_table('weather_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('source_label', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('url', sa.String(length=400), nullable=True),
    sa.Column('pdf_sha256', sa.String(length=64), nullable=True),
    sa.Column('pdf_path', sa.String(length=300), nullable=True),
    sa.Column('text_excerpt', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('origin', sa.String(length=10), nullable=False),
    sa.Column('summary_en', sa.String(length=480), nullable=True),
    sa.Column('summary_sw', sa.String(length=480), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('approved_by', sa.String(length=60), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pdf_sha256')
    )
    op.create_table('sacco',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('county', sa.String(length=60), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('insurer_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurer.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('officer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sacco_id', sa.Integer(), nullable=True),
    sa.Column('insurer_id', sa.Integer(), nullable=True),
    sa.Column('username', sa.String(length=60), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurer.id'], ),
    sa.ForeignKeyConstraint(['sacco_id'], ['sacco.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('premium_remittance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('sacco_id', sa.Integer(), nullable=False),
    sa.Column('insurer_id', sa.Integer(), nullable=False),
    sa.Column('amount_kes', sa.Float(), nullable=False),
    sa.Column('remitted_on', sa.Date(), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('reference', sa.String(length=40), nullable=False),
    sa.Column('period', sa.String(length=20), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('recorded_by', sa.String(length=60), nullable=False),
    sa.Column('reviewed_by', sa.String(length=60), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurer.id'], ),
    sa.ForeignKeyConstraint(['sacco_id'], ['sacco.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    with op.batch_alter_table('premium_remittance', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_premium_remittance_insurer_id'), ['insurer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_premium_remittance_sacco_id'), ['sacco_id'], unique=False)

    op.create_table('farmer',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('sacco_id', sa.Integer(), nullable=False),
    sa.Column('member_no', sa.String(length=40), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('national_id_enc', sa.Text(), nullable=False),
    sa.Column('national_id_hash', sa.String(length=64), nullable=False),
    sa.Column('national_id_masked', sa.String(length=16), nullable=False),
    sa.Column('phone_enc', sa.Text(), nullable=False),
    sa.Column('phone_hash', sa.String(length=64), nullable=False),
    sa.Column('phone_masked', sa.String(length=24), nullable=False),
    sa.Column('gender', sa.String(length=16), nullable=False),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('kiamis_status', sa.String(length=20), nullable=False),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['officer.id'], ),
    sa.ForeignKeyConstraint(['sacco_id'], ['sacco.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sacco_id', 'member_no'),
    sa.UniqueConstraint('sacco_id', 'national_id_hash')
    )
    with op.batch_alter_table('farmer', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_farmer_national_id_hash'), ['national_id_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_farmer_phone_hash'), ['phone_hash'], unique=False)

    op.create_table('consent',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('purpose', sa.String(length=40), nullable=False),
    sa.Column('granted', sa.Boolean(), nullable=False),
    sa.Column('wording_version', sa.String(length=20), nullable=False),
    sa.Column('wording_sha256', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('captured_by', sa.Integer(), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['captured_by'], ['officer.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('plot',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('crop', sa.String(length=30), nullable=False),
    sa.Column('acreage', sa.Float(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('polygon_geojson', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('policy',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('policy_no', sa.String(length=40), nullable=False),
    sa.Column('insurer_policy_number', sa.String(length=60), nullable=True),
    sa.Column('pay_ref', sa.String(length=12), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('plot_id', sa.String(length=32), nullable=False),
    sa.Column('sacco_id', sa.Integer(), nullable=False),
    sa.Column('insurer_id', sa.Integer(), nullable=True),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('season', sa.String(length=4), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('layers', sa.String(length=8), nullable=False),
    sa.Column('acres', sa.Float(), nullable=False),
    sa.Column('sum_insured_per_acre', sa.Float(), nullable=True),
    sa.Column('gross_kes', sa.Float(), nullable=False),
    sa.Column('government_share_kes', sa.Float(), nullable=False),
    sa.Column('farmer_share_kes', sa.Float(), nullable=False),
    sa.Column('resilience_points', sa.Float(), nullable=False),
    sa.Column('discount_kes', sa.Float(), nullable=False),
    sa.Column('discount_funder', sa.String(length=20), nullable=False),
    sa.Column('farmer_pays_kes', sa.Float(), nullable=False),
    sa.Column('amount_due_kes', sa.Integer(), nullable=False),
    sa.Column('paid_kes', sa.Float(), nullable=False),
    sa.Column('refund_due_kes', sa.Float(), nullable=False),
    sa.Column('sales_closes_on', sa.Date(), nullable=False),
    sa.Column('cover_active_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('subsidy_status', sa.String(length=20), nullable=False),
    sa.Column('payment_route', sa.String(length=20), nullable=False),
    sa.Column('payment_status', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('loan_linked', sa.Boolean(), nullable=False),
    sa.Column('loan_ref', sa.String(length=40), nullable=True),
    sa.Column('quote_id', sa.String(length=40), nullable=False),
    sa.Column('quote_snapshot', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['officer.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurer.id'], ),
    sa.ForeignKeyConstraint(['plot_id'], ['plot.id'], ),
    sa.ForeignKeyConstraint(['sacco_id'], ['sacco.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pay_ref'),
    sa.UniqueConstraint('plot_id', 'season', 'year'),
    sa.UniqueConstraint('policy_no')
    )
    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_insurer_id'), ['insurer_id'], unique=False)

    op.create_table('missed_payout_report',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=True),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('season', sa.String(length=4), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=24), nullable=False),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('index_snapshot', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('outcome', sa.String(length=30), nullable=True),
    sa.Column('review_note', sa.String(length=500), nullable=True),
    sa.Column('reviewed_by', sa.String(length=60), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reported_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    op.create_table('mpesa_request',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=False),
    sa.Column('amount_kes', sa.Integer(), nullable=False),
    sa.Column('phone_masked', sa.String(length=24), nullable=False),
    sa.Column('merchant_request_id', sa.String(length=60), nullable=False),
    sa.Column('checkout_request_id', sa.String(length=60), nullable=False),
    sa.Column('environment', sa.String(length=12), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('result_code', sa.Integer(), nullable=True),
    sa.Column('result_desc', sa.String(length=200), nullable=True),
    sa.Column('receipt', sa.String(length=30), nullable=True),
    sa.Column('requested_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('checkout_request_id')
    )
    op.create_table('payment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=False),
    sa.Column('amount_kes', sa.Float(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=40), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('within_window', sa.Boolean(), nullable=False),
    sa.Column('recorded_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reference')
    )
    op.create_table('payout',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('share', sa.Float(), nullable=True),
    sa.Column('amount_kes', sa.Float(), nullable=False),
    sa.Column('ward_status_id', sa.Integer(), nullable=False),
    sa.Column('index_version', sa.String(length=20), nullable=False),
    sa.Column('confirmed_on', sa.Date(), nullable=False),
    sa.Column('due_by', sa.Date(), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('approved_by', sa.String(length=60), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('hold_reason', sa.String(length=300), nullable=True),
    sa.Column('voucher_code', sa.String(length=16), nullable=True),
    sa.Column('reference', sa.String(length=40), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_by', sa.String(length=60), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.ForeignKeyConstraint(['ward_status_id'], ['ward_status.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('policy_id', 'kind'),
    sa.UniqueConstraint('voucher_code')
    )
    op.create_table('sms_message',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=True),
    sa.Column('template', sa.String(length=30), nullable=False),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('body', sa.String(length=320), nullable=False),
    sa.Column('dedupe_key', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=True),
    sa.Column('provider_message_id', sa.String(length=80), nullable=True),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )


def downgrade() -> None:
    op.drop_table('sms_message')
    op.drop_table('payout')
    op.drop_table('payment')
    op.drop_table('mpesa_request')
    op.drop_table('missed_payout_report')
    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_insurer_id'))

    op.drop_table('policy')
    op.drop_table('plot')
    op.drop_table('consent')
    with op.batch_alter_table('farmer', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_farmer_phone_hash'))
        batch_op.drop_index(batch_op.f('ix_farmer_national_id_hash'))

    op.drop_table('farmer')
    with op.batch_alter_table('premium_remittance', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_premium_remittance_sacco_id'))
        batch_op.drop_index(batch_op.f('ix_premium_remittance_insurer_id'))

    op.drop_table('premium_remittance')
    op.drop_table('officer')
    op.drop_table('sacco')
    op.drop_table('weather_item')
    with op.batch_alter_table('weather_fetch', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_weather_fetch_source'))

    op.drop_table('weather_fetch')
    with op.batch_alter_table('ward_status', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ward_status_ward_id'))

    op.drop_table('ward_status')
    op.drop_table('public_enquiry')
    op.drop_table('kiamis_record')
    op.drop_table('insurer')
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_event_at'))

    op.drop_table('audit_event')
