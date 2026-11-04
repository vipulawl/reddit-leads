from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
    _add_missing_columns()


ADDED_COLUMNS = {
    "projects": {"competitors": "JSON DEFAULT '[]'"},
    "leads": {
        "intent": "VARCHAR(20) DEFAULT ''", "reason": "TEXT DEFAULT ''",
        "urgent": "BOOLEAN DEFAULT FALSE", "answered": "BOOLEAN DEFAULT FALSE", "num_comments": "INTEGER DEFAULT 0",
        "replies": "JSON DEFAULT '[]'", "matched_comments": "JSON DEFAULT '[]'",
        "corrected_intent": "VARCHAR(20)", "embedding": "JSON",
    },
}


def _add_missing_columns():
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in ADDED_COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
