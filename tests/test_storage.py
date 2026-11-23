"""Database schema and connection behavior."""

import sqlite3
from pathlib import Path

import pytest

from internship_bot.storage import database, initialize_database


def test_schema_is_idempotent_and_tracks_delivery(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        connection.execute(
            """INSERT INTO jobs (
                canonical_key, title, company, location, apply_url, remote, internship,
                first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "key",
                "Backend Intern",
                "Example",
                "Remote India",
                "https://example.com",
                1,
                1,
                "2026-11-20T00:00:00Z",
                "2026-11-20T00:00:00Z",
            ),
        )
    initialize_database(path)
    with database(path) as connection:
        row = connection.execute(
            "SELECT status, sent_at, first_seen, last_seen FROM jobs WHERE canonical_key = 'key'"
        ).fetchone()
        assert row == ("open", None, "2026-11-20T00:00:00Z", "2026-11-20T00:00:00Z")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO source_listings (source, source_id, job_id, apply_url, last_seen) "
                "VALUES ('example', '123', 999, 'https://example.com', '2026-11-20T00:00:00Z')"
            )


def test_existing_source_listings_gain_active_column(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE source_listings (
            source TEXT, source_id TEXT, job_id INTEGER, apply_url TEXT, last_seen TEXT,
            PRIMARY KEY (source, source_id))"""
        )
        connection.execute(
            "INSERT INTO source_listings VALUES ('board', 'one', 1, 'https://example.com', 'now')"
        )
    initialize_database(path)
    with database(path) as connection:
        assert connection.execute("SELECT active FROM source_listings").fetchone() == (1,)
