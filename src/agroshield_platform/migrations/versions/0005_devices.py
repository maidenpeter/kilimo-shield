"""Phase 4 (milestone 9): hardware layer. Field devices, their messages, readings, photos, issues and the LoRaWAN
network server integration. New tables only; nothing existing changes.

Revision id 0005 follows main's 0004 (photos) once merged; it is written against 0003, and the integrator re-points
down_revision.

Revision ID: 0005
Revises: 0004a
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('device',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('ward_id', sa.String(length=40), nullable=False),
    sa.Column('site_type', sa.String(length=20), nullable=False),
    sa.Column('site_label', sa.String(length=120), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('secret_hash', sa.String(length=64), nullable=False),
    sa.Column('dev_eui', sa.String(length=16), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('firmware', sa.String(length=40), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_battery_v', sa.Float(), nullable=True),
    sa.Column('last_signal_dbm', sa.Float(), nullable=True),
    sa.Column('last_error', sa.String(length=200), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dev_eui'),
    sa.UniqueConstraint('uid')
    )
    with op.batch_alter_table('device', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_ward_id'), ['ward_id'], unique=False)

    op.create_table('device_integration',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('secret_hash', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    op.create_table('device_issue',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('msg_id', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.String(length=300), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['device.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('device_issue', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_issue_at'), ['at'], unique=False)
        batch_op.create_index(batch_op.f('ix_device_issue_device_id'), ['device_id'], unique=False)

    op.create_table('device_message',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('msg_id', sa.String(length=64), nullable=False),
    sa.Column('transport', sa.String(length=10), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload_sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['device.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_id', 'msg_id')
    )
    with op.batch_alter_table('device_message', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_message_device_id'), ['device_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_device_message_observed_at'), ['observed_at'], unique=False)

    op.create_table('device_image',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('path', sa.String(length=300), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('gcc', sa.Float(), nullable=False),
    sa.Column('exg', sa.Float(), nullable=False),
    sa.Column('green_fraction', sa.Float(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['device.id'], ),
    sa.ForeignKeyConstraint(['message_id'], ['device_message.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id')
    )
    with op.batch_alter_table('device_image', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_image_device_id'), ['device_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_device_image_observed_at'), ['observed_at'], unique=False)

    op.create_table('device_reading',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=32), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['device.id'], ),
    sa.ForeignKeyConstraint(['message_id'], ['device_message.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('device_reading', schema=None) as batch_op:
        batch_op.create_index('ix_device_reading_series', ['device_id', 'metric', 'observed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_device_reading_message_id'), ['message_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('device_reading', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_reading_message_id'))
        batch_op.drop_index('ix_device_reading_series')
    op.drop_table('device_reading')
    with op.batch_alter_table('device_image', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_image_observed_at'))
        batch_op.drop_index(batch_op.f('ix_device_image_device_id'))
    op.drop_table('device_image')
    with op.batch_alter_table('device_message', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_message_observed_at'))
        batch_op.drop_index(batch_op.f('ix_device_message_device_id'))
    op.drop_table('device_message')
    with op.batch_alter_table('device_issue', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_issue_device_id'))
        batch_op.drop_index(batch_op.f('ix_device_issue_at'))
    op.drop_table('device_issue')
    op.drop_table('device_integration')
    with op.batch_alter_table('device', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_ward_id'))
    op.drop_table('device')
