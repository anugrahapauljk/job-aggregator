"""SQLite connection lifetime and schema initialization."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path


@contextmanager
def database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys enabled and always close it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: Path) -> None:
    """Create missing tables without changing existing records."""
    schema = files("internship_bot.storage").joinpath("schema.sql").read_text(encoding="utf-8")
    with database(path) as connection:
        connection.executescript(schema)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(source_listings)")}
        if "active" not in columns:
            connection.execute(
                "ALTER TABLE source_listings ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
            )
