"""Upsert grouped listings while preserving delivery and first-seen history."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from internship_bot.models import Job
from internship_bot.pipeline import JobGroup, same_job


@dataclass(frozen=True, slots=True)
class StoreStats:
    inserted: int = 0
    updated: int = 0
    source_listings: int = 0


def _known_jobs(connection: sqlite3.Connection) -> list[tuple[int, Job]]:
    rows = connection.execute("SELECT id, title, company, location, remote FROM jobs").fetchall()
    return [
        (
            row[0],
            Job(
                source="stored",
                source_id=str(row[0]),
                title=row[1],
                company=row[2],
                location=row[3],
                description="",
                apply_url="",
                remote=bool(row[4]),
            ),
        )
        for row in rows
    ]


def _existing_ids(connection: sqlite3.Connection, group: JobGroup) -> set[int]:
    found: set[int] = set()
    for listing in group.listings:
        row = connection.execute(
            "SELECT job_id FROM source_listings WHERE source = ? AND source_id = ?",
            (listing.source, listing.source_id),
        ).fetchone()
        if row:
            found.add(int(row[0]))
    row = connection.execute(
        "SELECT id FROM jobs WHERE canonical_key = ?", (group.canonical_key,)
    ).fetchone()
    if row:
        found.add(int(row[0]))
    return found


def _merge_jobs(connection: sqlite3.Connection, survivor: int, duplicates: set[int]) -> None:
    for duplicate in duplicates - {survivor}:
        first, sent = connection.execute(
            "SELECT first_seen, sent_at FROM jobs WHERE id = ?", (duplicate,)
        ).fetchone()
        connection.execute(
            "UPDATE jobs SET first_seen = MIN(first_seen, ?), "
            "sent_at = CASE WHEN sent_at IS NULL THEN ? "
            "WHEN ? IS NULL THEN sent_at ELSE MIN(sent_at, ?) END WHERE id = ?",
            (first, sent, sent, sent, survivor),
        )
        connection.execute(
            "UPDATE source_listings SET job_id = ? WHERE job_id = ?", (survivor, duplicate)
        )
        connection.execute("DELETE FROM jobs WHERE id = ?", (duplicate,))


def upsert_jobs(
    connection: sqlite3.Connection,
    groups: list[JobGroup],
    fuzzy_threshold: int,
    now: datetime | None = None,
) -> StoreStats:
    """Save filtered jobs and every source alias; never change sent_at on a normal refresh."""
    seen_at = (now or datetime.now(UTC)).isoformat()
    known = _known_jobs(connection)
    inserted = updated = aliases = 0
    for group in groups:
        ids = _existing_ids(connection, group)
        ids.update(
            job_id
            for job_id, stored in known
            if any(same_job(stored, member, fuzzy_threshold) for member in group.listings)
        )
        if ids:
            job_id = min(ids)
            if len(ids) > 1:
                _merge_jobs(connection, job_id, ids)
                known = [(existing_id, job) for existing_id, job in known if existing_id not in ids]
            known = [(existing_id, job) for existing_id, job in known if existing_id != job_id]
            known.append((job_id, group.primary))
            connection.execute(
                """UPDATE jobs SET title = ?, company = ?, location = ?, description = ?,
                apply_url = ?, posted_at = ?, stipend_inr_per_month = ?, remote = ?,
                internship = ?, india_eligible = ?, score = ?, last_seen = ?, status = 'open'
                WHERE id = ?""",
                (
                    group.primary.title,
                    group.primary.company,
                    group.primary.location,
                    group.primary.description,
                    group.primary.apply_url,
                    group.primary.posted_at.isoformat() if group.primary.posted_at else None,
                    group.primary.stipend_inr_per_month,
                    int(group.primary.remote),
                    int(group.primary.internship),
                    group.primary.india_eligible,
                    group.score,
                    seen_at,
                    job_id,
                ),
            )
            updated += 1
        else:
            cursor = connection.execute(
                """INSERT INTO jobs (
                canonical_key, title, company, location, description, apply_url, posted_at,
                stipend_inr_per_month, remote, internship, india_eligible, score,
                first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    group.canonical_key,
                    group.primary.title,
                    group.primary.company,
                    group.primary.location,
                    group.primary.description,
                    group.primary.apply_url,
                    group.primary.posted_at.isoformat() if group.primary.posted_at else None,
                    group.primary.stipend_inr_per_month,
                    int(group.primary.remote),
                    int(group.primary.internship),
                    group.primary.india_eligible,
                    group.score,
                    seen_at,
                    seen_at,
                ),
            )
            assert cursor.lastrowid is not None
            job_id = int(cursor.lastrowid)
            known.append((job_id, group.primary))
            inserted += 1
        for listing in group.listings:
            connection.execute(
                """INSERT INTO source_listings
                (source, source_id, job_id, apply_url, last_seen, active)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(source, source_id) DO UPDATE SET
                job_id = excluded.job_id, apply_url = excluded.apply_url,
                last_seen = excluded.last_seen, active = 1""",
                (listing.source, listing.source_id, job_id, listing.apply_url, seen_at),
            )
            aliases += 1
    return StoreStats(inserted, updated, aliases)
