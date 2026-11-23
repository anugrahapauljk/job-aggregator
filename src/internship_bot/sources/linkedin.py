"""LinkedIn public guest listings through python-jobspy."""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as Date
from datetime import time as Time
from pathlib import Path
from typing import Any

import httpx

from internship_bot.models import Job
from internship_bot.sources.parsing import number, plain_text, string

logger = logging.getLogger(__name__)
_REMOTE = re.compile(r"\b(?:remote|work from home|wfh)\b", re.I)
_NOT_REMOTE = re.compile(r"\b(?:not remote|no remote|on.site only|in.office|hybrid)\b", re.I)


def _scrape(term: str, results_wanted: int, hours_old: int) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs

    kwargs: dict[str, Any] = {
        "site_name": ["linkedin"],
        "search_term": term,
        "location": "India",
        "job_type": "internship",
        "is_remote": True,
        "results_wanted": results_wanted,
        "hours_old": hours_old,
        "fetch_description": True,
        "description_format": "plain",
        "verbose": 0,
    }
    proxies = os.getenv("JOBSPY_PROXIES", "").strip()
    if proxies:
        kwargs["proxies"] = [proxy.strip() for proxy in proxies.split(",") if proxy.strip()]
    frame = scrape_jobs(**kwargs)
    return frame.to_dict(orient="records") if frame is not None else []


def _posted(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC)
    if isinstance(value, Date):
        return datetime.combine(value, Time.min, tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=parsed.tzinfo or UTC)
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class LinkedInSource:
    search_terms: tuple[str, ...]
    results_per_query: int = 10
    hours_old: int = 168
    request_delay_seconds: float = 2.0
    cache_ttl_minutes: int = 60
    cache_dir: Path | None = None
    name: str = "linkedin"
    complete_inventory: bool = False

    def _rows(self, term: str) -> list[dict[str, Any]]:
        key = hashlib.sha256(
            f"{term}:{self.results_per_query}:{self.hours_old}".encode()
        ).hexdigest()
        path = self.cache_dir / f"linkedin-{key}.json" if self.cache_dir else None
        if path is not None and self.cache_ttl_minutes:
            try:
                if time.time() - path.stat().st_mtime < self.cache_ttl_minutes * 60:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(cached, list):
                        return [row for row in cached if isinstance(row, dict)]
            except (OSError, ValueError):
                pass
        rows = _scrape(term, self.results_per_query, self.hours_old)
        if path is not None and self.cache_ttl_minutes:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, default=str), encoding="utf-8")
        return rows

    def fetch(self, client: httpx.Client) -> list[Job]:
        del client  # JobSpy owns its HTTP transport.
        jobs: dict[str, Job] = {}
        failures: list[str] = []
        succeeded = 0
        for index, term in enumerate(self.search_terms):
            if index:
                time.sleep(self.request_delay_seconds)
            try:
                rows = self._rows(term)
            except Exception as exc:
                failures.append(f"{term}: {type(exc).__name__}: {exc}")
                continue
            if rows:
                succeeded += 1
            else:
                failures.append(f"{term}: no listings returned (possibly rate limited)")
            for row in rows:
                title = string(row.get("title"))
                company = string(row.get("company"))
                url = string(row.get("job_url"))
                if not title or not company or not url:
                    continue
                location = string(row.get("location"))
                description = plain_text(row.get("description"))
                remote_evidence = f"{title} {location} {description}".casefold()
                remote = bool(row.get("is_remote")) and bool(_REMOTE.search(remote_evidence))
                if _NOT_REMOTE.search(remote_evidence):
                    remote = False
                place = location.casefold()
                india_eligible = any(
                    marker in place for marker in ("india", "worldwide", "anywhere")
                )
                source_id = string(row.get("id")) or url
                jobs[source_id] = Job(
                    source=self.name,
                    source_id=source_id,
                    title=title,
                    company=company,
                    location=location,
                    description=description,
                    apply_url=url,
                    posted_at=_posted(row.get("date_posted")),
                    salary_min=number(row.get("min_amount")),
                    salary_max=number(row.get("max_amount")),
                    salary_currency=string(row.get("currency")) or None,
                    salary_period=string(row.get("interval")) or None,
                    remote=remote,
                    india_eligible=india_eligible,
                )
        if succeeded == 0:
            raise RuntimeError("LinkedIn returned no usable results: " + "; ".join(failures))
        if failures:
            logger.warning("LinkedIn partial fetch: %s", "; ".join(failures))
        return list(jobs.values())
