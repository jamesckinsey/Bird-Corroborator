from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import Settings

class Base(DeclarativeBase): pass

def make_engine(settings: Settings):
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///" )).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def pragmas(conn, _):
            cur = conn.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.execute("PRAGMA journal_mode=WAL"); cur.close()
    return engine

def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
