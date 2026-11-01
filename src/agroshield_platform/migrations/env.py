"""Alembic environment for the AgroShield portal database.

Run through agroshield_platform.migrate (init_db, `agroshield-portal db ...`) or the alembic CLI from the repo root
(alembic.ini). The database URL comes from the connection the caller passes, else from DATABASE_URL / the settings
default (var/agroshield.db). SQLite uses batch mode, so column and constraint changes work there too.
"""
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from agroshield_platform.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from agroshield_platform.settings import load_settings
    return load_settings().database_url


def run_offline() -> None:
    url = _url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"), compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = engine_from_config({"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()                      # so Alembic starts (and commits) its own transaction
        _run(conn, pragma=False)


def _run(connection, pragma: bool = True) -> None:
    if pragma and connection.dialect.name == "sqlite":
        # Batch mode rebuilds a table by copy, drop and rename; with foreign keys enforced, SQLite refuses to drop a
        # table other tables point at. Off for this connection only (migrate.upgrade drops it from the pool after).
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
