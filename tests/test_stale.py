"""Closure depends on successful source coverage and posting age."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from internship_bot.models import Job
from internship_bot.sources.base import SourceResult
from internship_bot.storage import database, initialize_database
from internship_bot.storage.stale import update_stale


def _listing(source: str, source_id: str) -> Job:
    return Job(
        source, source_id, "Backend Intern", "Example", "Remote India", "", "https://example.com"
    )


def test_failed_full_inventory_does_not_close_and_other_alias_keeps_open(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        connection.execute(
            """INSERT INTO jobs (canonical_key, title, company, location, apply_url,
            remote, internship, first_seen, last_seen)
            VALUES ('one', 'Backend Intern', 'Example', 'Remote India',
            'https://example.com', 1, 1, '2026-11-20', '2026-11-20')"""
        )
        for source in ("greenhouse:example", "lever:example"):
            connection.execute(
                """INSERT INTO source_listings (source, source_id, job_id, apply_url, last_seen)
                VALUES (?, 'one', 1, 'https://example.com', '2026-11-20')""",
                (source,),
            )
        failed = SourceResult("greenhouse:example", "failed", [], complete_inventory=True)
        assert update_stale(connection, [failed], 30) == 0
        assert connection.execute("SELECT status FROM jobs").fetchone() == ("open",)
        empty = SourceResult("greenhouse:example", "success", [], complete_inventory=True)
        assert update_stale(connection, [empty, failed], 30) == 0
        assert connection.execute("SELECT status FROM jobs").fetchone() == ("open",)
        other_empty = SourceResult("lever:example", "success", [], complete_inventory=True)
        assert update_stale(connection, [other_empty], 30) == 1
        assert connection.execute("SELECT status FROM jobs").fetchone() == ("closed",)


def test_capped_source_expires_by_posting_age_only_after_success(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    now = datetime(2026, 11, 23, tzinfo=UTC)
    old = now - timedelta(days=40)
    initialize_database(path)
    with database(path) as connection:
        connection.execute(
            """INSERT INTO jobs (canonical_key, title, company, location, apply_url,
            remote, internship, posted_at, first_seen, last_seen)
            VALUES ('one', 'Backend Intern', 'Example', 'Remote India',
            'https://example.com', 1, 1, ?, ?, ?)""",
            (old.isoformat(), old.isoformat(), old.isoformat()),
        )
        connection.execute(
            """INSERT INTO source_listings (source, source_id, job_id, apply_url, last_seen)
            VALUES ('remoteok', 'one', 1, 'https://example.com', ?)""",
            (now.isoformat(),),
        )
        failed = SourceResult("remoteok", "failed", [], complete_inventory=False)
        assert update_stale(connection, [failed], 30, now) == 0
        success = SourceResult("remoteok", "success", [], complete_inventory=False)
        assert update_stale(connection, [success], 30, now) == 1
        assert connection.execute("SELECT status FROM jobs").fetchone() == ("closed",)
