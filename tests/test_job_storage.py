"""Persistent cross-source identity and sent history."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from internship_bot.config import load_config
from internship_bot.models import Job
from internship_bot.pipeline import group_jobs
from internship_bot.storage import database, initialize_database
from internship_bot.storage.jobs import upsert_jobs


def test_aliases_and_sent_history_survive_refresh(tmp_path: Path) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    now = datetime(2026, 11, 23, tzinfo=UTC)
    original = Job(
        source="internshala",
        source_id="42",
        title="Backend Intern",
        company="Example Pvt Ltd",
        location="Remote India",
        description="Python APIs",
        apply_url="https://example.com/one",
        posted_at=now,
        remote=True,
        india_eligible=True,
    )
    alias = replace(
        original,
        source="linkedin",
        source_id="99",
        title="Backend Intern (Remote)",
        company="Example Technologies",
        apply_url="https://example.com/two",
    )
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        first = upsert_jobs(connection, group_jobs([original, alias], config, now), 86, now)
        assert first.inserted == 1 and first.source_listings == 2
        connection.execute("UPDATE jobs SET sent_at = ?", (now.isoformat(),))
    later = now + timedelta(days=1)
    renamed = replace(original, title="Backend Developer Intern", posted_at=later)
    with database(path) as connection:
        second = upsert_jobs(connection, group_jobs([renamed], config, later), 86, later)
        assert second.updated == 1 and second.inserted == 0
        job = connection.execute(
            "SELECT first_seen, last_seen, sent_at, status FROM jobs"
        ).fetchone()
        aliases = connection.execute("SELECT source, job_id FROM source_listings").fetchall()
    assert job == (now.isoformat(), later.isoformat(), now.isoformat(), "open")
    assert len(aliases) == 2 and aliases[0][1] == aliases[1][1]


def test_merge_preserves_sent_marker(tmp_path: Path) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    now = datetime(2026, 11, 23, tzinfo=UTC)
    with database(path) as connection:
        for key, title, sent in (
            ("old-one", "Backend Intern", None),
            ("old-two", "Backend Intern Remote", now.isoformat()),
        ):
            connection.execute(
                """INSERT INTO jobs (
                canonical_key, title, company, location, apply_url, remote, internship,
                first_seen, last_seen, sent_at
                ) VALUES (?, ?, 'Example', 'Remote India', 'https://example.com', 1, 1, ?, ?, ?)""",
                (key, title, now.isoformat(), now.isoformat(), sent),
            )
        connection.execute(
            """INSERT INTO source_listings (source, source_id, job_id, apply_url, last_seen)
            VALUES ('linkedin', 'old', 2, 'https://example.com', ?)""",
            (now.isoformat(),),
        )
        incoming = Job(
            source="internshala",
            source_id="new",
            title="Backend Intern",
            company="Example",
            location="Remote India",
            description="Python",
            apply_url="https://example.com/new",
            remote=True,
            india_eligible=True,
        )
        upsert_jobs(connection, group_jobs([incoming], config, now), 86, now)
        rows = connection.execute("SELECT id, sent_at FROM jobs").fetchall()
        aliases = connection.execute("SELECT DISTINCT job_id FROM source_listings").fetchall()
    assert rows == [(1, now.isoformat())]
    assert aliases == [(1,)]
