"""Fetch each source independently and record its outcome."""

import logging
import sqlite3
import time
from datetime import UTC, datetime

import httpx

from internship_bot.sources.base import Source, SourceResult, SourceSkipped
from internship_bot.sources.http import _retry_after

logger = logging.getLogger(__name__)


def fetch_all(
    sources: list[Source],
    client: httpx.Client,
    connection: sqlite3.Connection | None = None,
    max_attempts: int = 3,
) -> list[SourceResult]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    results: list[SourceResult] = []
    for source in sources:
        started = datetime.now(UTC).isoformat()
        try:
            for attempt in range(max_attempts):
                try:
                    jobs = source.fetch(client)
                    break
                except SourceSkipped:
                    raise
                except Exception as exc:
                    response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
                    transient_status = response is not None and response.status_code in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    retryable = (
                        isinstance(exc, httpx.TransportError)
                        or transient_status
                        or (source.name == "linkedin" and isinstance(exc, RuntimeError))
                    )
                    if not retryable or attempt == max_attempts - 1:
                        raise
                    after = _retry_after(response.headers.get("Retry-After")) if response else None
                    if after is not None and after > 30:
                        raise
                    time.sleep(after if after is not None else 2.0**attempt)
            result = SourceResult(
                source.name,
                "success",
                jobs,
                len(jobs),
                complete_inventory=source.complete_inventory,
            )
            logger.info("%s: fetched %d jobs", source.name, len(jobs))
        except SourceSkipped as exc:
            result = SourceResult(source.name, "skipped", [], warning=str(exc))
            logger.warning("%s: skipped: %s", source.name, exc)
        except Exception as exc:
            result = SourceResult(source.name, "failed", [], warning=str(exc))
            logger.exception("%s: fetch failed", source.name)
        results.append(result)
        if connection is not None:
            connection.execute(
                """INSERT INTO source_runs
                (source, started_at, finished_at, status, raw_count, error)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    source.name,
                    started,
                    datetime.now(UTC).isoformat(),
                    result.status,
                    result.raw_count,
                    result.warning,
                ),
            )
            connection.commit()
    return results
