"""Phase 1 review fix: the same KMD PDF may be held once for every SACCO and once per SACCO.

weather_item.pdf_sha256 was unique across all advisories, so a PDF a manager uploaded for one SACCO stopped the
every-SACCO copy from being created (and the other way round). It is now an ordinary index; weather.store_pdf
keeps it unique within each audience.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

# SQLite reflects the old constraint without a name; this convention gives it one inside batch mode.
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def _old_unique_name() -> str:
    return "uq_weather_item_pdf_sha256" if op.get_bind().dialect.name == "sqlite" else "weather_item_pdf_sha256_key"


def upgrade() -> None:
    with op.batch_alter_table('weather_item', naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint(_old_unique_name(), type_='unique')
        batch_op.create_index(batch_op.f('ix_weather_item_pdf_sha256'), ['pdf_sha256'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('weather_item', naming_convention=NAMING) as batch_op:
        batch_op.drop_index(batch_op.f('ix_weather_item_pdf_sha256'))
        batch_op.create_unique_constraint(_old_unique_name(), ['pdf_sha256'])
