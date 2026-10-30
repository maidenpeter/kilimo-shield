"""Database migrations (Alembic): every schema change is a revision in migrations/versions, so a database with real
data is upgraded in place and never needs a reset.

    upgrade(engine)   bring any database to the newest revision (called by db.init_db on every start)
    status(engine)    the database's revision and the newest one

Three cases on start:
  empty database          tables created from the models and stamped at the newest revision (the same schema the
                          revisions build; a test keeps the two identical)
  managed by Alembic      pending revisions applied (a SQLite file is copied to <name>.pre-<revision>.bak first)
  created before Alembic  (by create_all, up to 30 October 2026): its tables and columns are matched against each
                          revision; it is stamped at the one it matches and upgraded from there. A database that
                          matches none is refused with a clear message, never changed.
"""
from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from .models import Base

HERE = Path(__file__).parent / "migrations"
log = logging.getLogger("agroshield.migrate")


class MigrationError(RuntimeError):
    pass


def config(connection=None, url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


@lru_cache(maxsize=1)
def scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(config())


def head() -> str:
    return scripts().get_current_head()


def _shape(conn) -> dict[str, set[str]]:
    insp = inspect(conn)
    return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names() if t != "alembic_version"}


@lru_cache(maxsize=None)
def _shape_at(revision: str) -> dict[str, frozenset[str]]:
    """Tables and columns the revisions build up to `revision` (in a throwaway in-memory database)."""
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        command.upgrade(config(conn), revision)
        return {t: frozenset(c) for t, c in _shape(conn).items()}


def _match(found: dict[str, set[str]]) -> str | None:
    """The revision whose tables and columns a pre-Alembic database has exactly (no missing or extra ones)."""
    for rev in (r.revision for r in scripts().walk_revisions()):     # newest first
        want = _shape_at(rev)
        if set(want) == set(found) and all(found[t] == set(cols) for t, cols in want.items()):
            return rev
    return None


def _backup(engine, rev: str | None) -> Path | None:
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    src = Path(url.database)
    if not src.exists():
        return None
    dst = src.with_name(f"{src.name}.pre-{head()}.bak")
    shutil.copy2(src, dst)
    log.warning("database at revision %s copied to %s before upgrading to %s", rev or "none", dst, head())
    return dst


def upgrade(engine) -> str:
    """Bring the database to the newest revision. Returns what happened: created, current, upgraded or adopted."""
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        current = MigrationContext.configure(conn).get_current_revision() if "alembic_version" in tables else None
    if "alembic_version" in tables and current == head():
        return "current"
    if not tables - {"alembic_version"}:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            MigrationContext.configure(conn).stamp(scripts(), "head")
        return "created"
    if "alembic_version" in tables:
        _backup(engine, current)
        with engine.begin() as conn:
            command.upgrade(config(conn), "head")
        engine.dispose()            # the migration connection had SQLite foreign keys off; never reuse it
        log.info("database upgraded from %s to %s", current, head())
        return "upgraded"
    with engine.connect() as conn:
        found = _shape(conn)
    rev = _match(found)
    if rev is None:
        raise MigrationError(
            "This database was created before migrations existed and its tables do not match any known revision, so it "
            "was not changed. Back it up, then either recreate it (development data) or ask for a one-off migration.")
    _backup(engine, None)
    with engine.begin() as conn:
        command.stamp(config(conn), rev)
        command.upgrade(config(conn), "head")
    engine.dispose()
    log.info("pre-migration database matched revision %s; upgraded to %s", rev, head())
    return "adopted"


def status(engine) -> dict:
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        current = MigrationContext.configure(conn).get_current_revision() if "alembic_version" in tables else None
    return {"current": current, "head": head(), "up_to_date": current == head()}
