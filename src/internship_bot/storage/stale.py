"""Close jobs only on evidence from a successful source fetch."""

import sqlite3
from datetime import UTC, datetime, timedelta

from internship_bot.sources.base import SourceResult


def update_stale(
    connection: sqlite3.Connection,
    results: list[SourceResult],
    max_age_days: int | None,
    now: datetime | None = None,
) -> int:
    """Retire missing full-inventory aliases or aged capped-source aliases."""
    now = now or datetime.now(UTC)
    if not any(result.status == "success" for result in results):
        return 0
    for result in results:
        if result.status != "success":
            continue
        if result.complete_inventory:
            present = {job.source_id for job in result.jobs}
            stored = connection.execute(
                "SELECT source_id FROM source_listings WHERE source = ? AND active = 1",
                (result.name,),
            ).fetchall()
            connection.executemany(
                "UPDATE source_listings SET active = 0 WHERE source = ? AND source_id = ?",
                [(result.name, source_id) for (source_id,) in stored if source_id not in present],
            )
        elif max_age_days is not None:
            cutoff = now - timedelta(days=max_age_days)
            rows = connection.execute(
                """SELECT sl.source_id, j.posted_at FROM source_listings AS sl
                JOIN jobs AS j ON j.id = sl.job_id
                WHERE sl.source = ? AND sl.active = 1 AND j.posted_at IS NOT NULL""",
                (result.name,),
            ).fetchall()
            connection.executemany(
                "UPDATE source_listings SET active = 0 WHERE source = ? AND source_id = ?",
                [
                    (result.name, source_id)
                    for source_id, posted_at in rows
                    if datetime.fromisoformat(posted_at.replace("Z", "+00:00")).astimezone(UTC)
                    < cutoff
                ],
            )
    cursor = connection.execute(
        """UPDATE jobs SET status = 'closed' WHERE status = 'open'
        AND EXISTS (SELECT 1 FROM source_listings WHERE job_id = jobs.id)
        AND NOT EXISTS (SELECT 1 FROM source_listings WHERE job_id = jobs.id AND active = 1)"""
    )
    return cursor.rowcount
