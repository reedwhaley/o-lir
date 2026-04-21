from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {'check_same_thread': False} if database_url.startswith('sqlite') else {}
    _engine = create_engine(database_url, future=True, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def create_all() -> None:
    if _engine is None:
        raise RuntimeError('Database not initialized')
    Base.metadata.create_all(bind=_engine)


@contextmanager
def session_scope():
    if _SessionLocal is None:
        raise RuntimeError('Database not initialized')
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
