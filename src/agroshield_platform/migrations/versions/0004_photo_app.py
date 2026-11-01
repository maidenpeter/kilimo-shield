"""Phase 3 (milestone 8): photo app users and champion assignments, photo points, photos, AI suggestions,
human reviews and picture-rider claims (ILLUSTRATIVE). New tables only; nothing existing changes.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=12), nullable=False),
    sa.Column('pin_hash', sa.String(length=200), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('farmer_id')
    )
    op.create_table('app_assignment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plot_id', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['plot_id'], ['plot.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'plot_id')
    )
    with op.batch_alter_table('app_assignment', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_app_assignment_user_id'), ['user_id'], unique=False)

    op.create_table('photo_point',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plot_id', sa.String(length=32), nullable=False),
    sa.Column('label', sa.String(length=40), nullable=False),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['plot_id'], ['plot.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('photo_point', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_photo_point_plot_id'), ['plot_id'], unique=False)

    op.create_table('rider_claim',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=False),
    sa.Column('reported_by', sa.Integer(), nullable=False),
    sa.Column('cause', sa.String(length=16), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('extent', sa.String(length=8), nullable=True),
    sa.Column('illustrative_amount_kes', sa.Float(), nullable=True),
    sa.Column('assessed_by', sa.String(length=60), nullable=True),
    sa.Column('assessed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.ForeignKeyConstraint(['reported_by'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    with op.batch_alter_table('rider_claim', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rider_claim_policy_id'), ['policy_id'], unique=False)

    op.create_table('photo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=12), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('plot_id', sa.String(length=32), nullable=False),
    sa.Column('farmer_id', sa.String(length=32), nullable=False),
    sa.Column('policy_id', sa.String(length=32), nullable=True),
    sa.Column('photo_point_id', sa.Integer(), nullable=True),
    sa.Column('taken_by', sa.Integer(), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('taken_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('phash', sa.String(length=16), nullable=False),
    sa.Column('file_path', sa.String(length=300), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('flags', sa.JSON(), nullable=False),
    sa.Column('on_schedule', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('reject_reason', sa.String(length=200), nullable=True),
    sa.Column('rider_claim_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmer.id'], ),
    sa.ForeignKeyConstraint(['photo_point_id'], ['photo_point.id'], ),
    sa.ForeignKeyConstraint(['plot_id'], ['plot.id'], ),
    sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], ),
    sa.ForeignKeyConstraint(['rider_claim_id'], ['rider_claim.id'], ),
    sa.ForeignKeyConstraint(['taken_by'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id'),
    sa.UniqueConstraint('ref')
    )
    with op.batch_alter_table('photo', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_photo_farmer_id'), ['farmer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_photo_phash'), ['phash'], unique=False)
        batch_op.create_index(batch_op.f('ix_photo_plot_id'), ['plot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_photo_sha256'), ['sha256'], unique=False)

    op.create_table('photo_suggestion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('photo_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('tag', sa.String(length=20), nullable=True),
    sa.Column('reason', sa.String(length=300), nullable=True),
    sa.Column('model', sa.String(length=40), nullable=True),
    sa.Column('sent_sha256', sa.String(length=64), nullable=True),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['photo_id'], ['photo.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('photo_suggestion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_photo_suggestion_photo_id'), ['photo_id'], unique=False)

    op.create_table('photo_review',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('photo_id', sa.Integer(), nullable=False),
    sa.Column('reviewer', sa.String(length=60), nullable=False),
    sa.Column('tag', sa.String(length=20), nullable=False),
    sa.Column('extent', sa.String(length=8), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('suggestion_id', sa.Integer(), nullable=True),
    sa.Column('suggestion_tag', sa.String(length=20), nullable=True),
    sa.Column('agreed_with_suggestion', sa.Boolean(), nullable=True),
    sa.Column('flags_cleared', sa.Boolean(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['photo_id'], ['photo.id'], ),
    sa.ForeignKeyConstraint(['suggestion_id'], ['photo_suggestion.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('photo_id')
    )


def downgrade() -> None:
    op.drop_table('photo_review')
    with op.batch_alter_table('photo_suggestion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_suggestion_photo_id'))

    op.drop_table('photo_suggestion')
    with op.batch_alter_table('photo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_sha256'))
        batch_op.drop_index(batch_op.f('ix_photo_plot_id'))
        batch_op.drop_index(batch_op.f('ix_photo_phash'))
        batch_op.drop_index(batch_op.f('ix_photo_farmer_id'))

    op.drop_table('photo')
    with op.batch_alter_table('rider_claim', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rider_claim_policy_id'))

    op.drop_table('rider_claim')
    with op.batch_alter_table('photo_point', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_point_plot_id'))

    op.drop_table('photo_point')
    with op.batch_alter_table('app_assignment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_app_assignment_user_id'))

    op.drop_table('app_assignment')
    op.drop_table('app_user')
