from .common import Repository, new_id, utcnow  # noqa: F401
from .memory import MemoryRepository  # noqa: F401


def make_repository(database_url: str):
    """Create the SQLAlchemy repository for the configured URL (SQLite default, PostgreSQL supported)."""
    from .sql_repository import SqlRepository  # imported lazily: requires SQLAlchemy

    return SqlRepository(database_url)
