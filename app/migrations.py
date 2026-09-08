"""Small additive schema versioning for the SQLite appliance."""
from datetime import datetime,timezone
from sqlalchemy import text
from app.database import Base
import app.db.models  # noqa: F401 - registers all table metadata before create_all
SCHEMA_VERSION=2
def initialize_database(engine):
    # create_all only adds missing tables/indexes; it never drops existing data.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)"))
        current=conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        if current is None or current < SCHEMA_VERSION:
            conn.execute(text("INSERT INTO schema_version(version,applied_at) VALUES (:v,:at)"),{"v":SCHEMA_VERSION,"at":datetime.now(timezone.utc).isoformat()})
