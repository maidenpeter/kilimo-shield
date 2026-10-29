"""Database engine and sessions, plus the audit helper."""
from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .crypto import scrub
from .models import AuditEvent, Base


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite enforces foreign keys only when asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def init_db(engine) -> sessionmaker:
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker):
    s: Session = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# System identifiers that contain long digit runs (dates, hashes) but never personal data.
SAFE_KEYS = {"quote_id", "policy_no", "file_sha256", "source_sha256", "index_versions"}


def audit(s: Session, actor: str, action: str, entity: str, entity_id: str | None = None, **details) -> None:
    """Append an audit event. Free-text details are scrubbed so no ID or phone number is stored in clear."""
    clean = {k: v if k in SAFE_KEYS else json.loads(scrub(json.dumps(v, default=str))) for k, v in details.items()}
    s.add(AuditEvent(actor=actor, action=action, entity=entity, entity_id=entity_id, details=clean))
