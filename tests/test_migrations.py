"""Remaining brief, Phase 2: Alembic migrations, so later phases and real data never need a reset.

- The revisions build exactly the schema the models describe (so a model change without a revision fails here).
- An empty database is created and stamped at the newest revision.
- The demo database as it was on 30 October 2026 (before migrations; fictional people) is adopted and upgraded in
  place, keeping every row, and the portal runs on it.
- A database that matches no revision is refused and left untouched.
- Downgrade and upgrade again work on SQLite.
"""
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from agroshield_platform import migrate
from agroshield_platform.db import init_db, make_engine
from agroshield_platform.models import Base

from conftest import REPO
from test_platform import book  # noqa: F401

DUMP = REPO / "tests" / "fixtures" / "demo_db_2026-10-30.sql"


def _load_dump(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(DUMP.read_text(encoding="utf-8"))
    con.close()


def _counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(path)
    out = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
           for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'") if t != "alembic_version"}
    con.close()
    return out


def test_revisions_build_exactly_the_model_schema():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        command.upgrade(migrate.config(conn), "head")
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diffs == [], f"models and migrations differ; add a revision: {diffs}"


def test_empty_database_is_created_and_stamped():
    eng = make_engine("sqlite://")
    assert migrate.upgrade(eng) == "created"
    assert migrate.status(eng) == {"current": migrate.head(), "head": migrate.head(), "up_to_date": True}
    with eng.connect() as conn:
        assert {t: frozenset(c) for t, c in migrate._shape(conn).items()} == migrate._shape_at(migrate.head())
    assert migrate.upgrade(eng) == "current"                               # a second start changes nothing


def test_the_30_october_demo_database_is_upgraded_in_place(tmp_path):
    db = tmp_path / "demo.db"
    _load_dump(db)
    before = _counts(db)
    assert before["policy"] == 12 and before["mpesa_request"] == 2 and "refund" not in before
    eng = make_engine(f"sqlite:///{db.as_posix()}")
    assert migrate._match({t: set(c) for t, c in migrate._shape(eng.connect()).items()}) == "0001"
    init_db(eng)
    assert migrate.status(eng)["up_to_date"]
    after = _counts(db)
    assert {t: n for t, n in after.items() if t in before} == before          # every row kept
    assert after["refund"] == 0
    assert (tmp_path / f"demo.db.pre-{migrate.head()}.bak").exists()           # a copy taken first
    with eng.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("mpesa_request")}
        assert {"query_attempts", "next_query_at", "callback_receipt", "resolution"} <= cols
        pending = conn.execute(text("SELECT COUNT(*), SUM(next_query_at IS NOT NULL), SUM(query_attempts) "
                                    "FROM mpesa_request WHERE status = 'pending'")).one()
        assert pending[0] == pending[1] >= 1 and pending[2] == 0              # queued for a status check, not dropped
        assert conn.execute(text("SELECT COUNT(*) FROM weather_item WHERE sacco_id IS NOT NULL")).scalar() == 0
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1           # enforced again after migrating


def test_the_portal_runs_on_the_upgraded_demo_database(tmp_path, book):  # noqa: F811
    import base64
    import re
    import secrets

    from agroshield_platform.cli import DEMO_PASSWORD
    from agroshield_platform.settings import Settings
    from agroshield_platform.web.app import create_app

    db = tmp_path / "demo.db"
    _load_dump(db)
    s = Settings(database_url=f"sqlite:///{db.as_posix()}", encryption_key=secrets.token_bytes(32),
                 lookup_key=secrets.token_bytes(32), session_secret=base64.b64encode(secrets.token_bytes(32)).decode(),
                 config_dir=REPO / "config", dev_keys=True)
    app = create_app(s, book)
    c = TestClient(app)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").text).group(1)
    r = c.post("/login", data={"username": "demo-manager", "password": DEMO_PASSWORD, "csrf_token": tok},
               follow_redirects=False)
    assert r.status_code == 303
    for page in ("/dashboard", "/members", "/reports", "/reports/premium", "/payouts", "/weather"):
        assert c.get(page).status_code == 200, page
    assert "Wanjiku Kamau (fictional)" in c.get("/members").text


def test_unknown_old_database_is_refused_and_untouched(tmp_path):
    db = tmp_path / "odd.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE policy (id TEXT PRIMARY KEY, something_else TEXT)")
    con.commit()
    con.close()
    before = db.read_bytes()
    with pytest.raises(migrate.MigrationError, match="not changed"):
        migrate.upgrade(make_engine(f"sqlite:///{db.as_posix()}"))
    assert db.read_bytes() == before and not list(tmp_path.glob("*.bak"))


def test_downgrade_and_upgrade_again(tmp_path):
    db = tmp_path / "demo.db"
    _load_dump(db)
    eng = make_engine(f"sqlite:///{db.as_posix()}")
    init_db(eng)
    before = _counts(db)
    with eng.begin() as conn:
        command.downgrade(migrate.config(conn), "0001")
    assert migrate.status(eng)["current"] == "0001" and "refund" not in _counts(db)
    with eng.begin() as conn:
        command.upgrade(migrate.config(conn), "head")
    assert migrate.status(eng)["up_to_date"] and _counts(db) == before


def test_alembic_ini_points_at_the_packaged_revisions():
    ini = (REPO / "alembic.ini").read_text(encoding="utf-8")
    assert "script_location = %(here)s/src/agroshield_platform/migrations" in ini
