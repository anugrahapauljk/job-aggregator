"""Retrieve open internships from Unstop's permitted public API."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from internship_bot.models import Job
from internship_bot.sources.http import get_json
from internship_bot.sources.parsing import (
    date,
    items,
    mapping,
    number,
    plain_text,
    required,
    string,
)

logger = logging.getLogger(__name__)
_URL = "https://unstop.com/api/public/opportunity/search-result"
_CURRENCIES = {"fa-rupee": "INR", "fa-inr": "INR", "fa-dollar": "USD"}
_PERIODS = {"monthly": "monthly", "month": "monthly", "annually": "yearly", "year": "yearly"}


def _names(value: Any) -> list[str]:
    entries = value if isinstance(value, list) else [value]
    return [
        string(mapping(entry).get("name") if isinstance(entry, dict) else entry)
        for entry in entries
        if entry
    ]


def _location(row: dict[str, Any]) -> str:
    places = [mapping(entry) for entry in row.get("locations") or []]
    cities = list(dict.fromkeys(string(place.get("city")) for place in places if place.get("city")))
    countries = list(
        dict.fromkeys(string(place.get("country")) for place in places if place.get("country"))
    )
    return ", ".join([*cities, *countries]) or string(row.get("location"))


@dataclass(frozen=True, slots=True)
class UnstopSource:
    max_results: int = 100
    search_terms: tuple[str, ...] = ()
    max_pages: int = 3
    max_age_days: int | None = 30
    request_delay_seconds: float = 1.0
    cache_ttl_minutes: int = 60
    cache_dir: Path | None = None
    name: str = "unstop"
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        jobs: dict[str, Job] = {}
        failures: list[str] = []
        succeeded = 0
        last_request = 0.0
        for term in self.search_terms or ("",):
            for page_number in range(1, self.max_pages + 1):
                if last_request:
                    time.sleep(
                        max(0, self.request_delay_seconds - (time.monotonic() - last_request))
                    )
                params: dict[str, str | int] = {
                    "opportunity": "internships",
                    "oppstatus": "open",
                    "per_page": 30,
                    "page": page_number,
                }
                if term:
                    params["searchTerm"] = term
                try:
                    payload = get_json(
                        client,
                        _URL,
                        params,
                        cache_dir=self.cache_dir,
                        cache_ttl_minutes=self.cache_ttl_minutes,
                    )
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    failures.append(f"{term or '*'} page {page_number}: {exc}")
                    break
                last_request = time.monotonic()
                succeeded += 1
                page_data = mapping(mapping(payload).get("data"))
                page = items(page_data.get("data"))
                for row in page:
                    try:
                        job = self._map(row)
                    except ValueError as exc:
                        logger.warning("Unstop: malformed record skipped: %s", exc)
                        continue
                    if job is not None:
                        jobs[job.source_id] = job
                    if len(jobs) >= self.max_results:
                        break
                if len(jobs) >= self.max_results:
                    break
                if page_number >= int(page_data.get("last_page") or page_number):
                    break
            if len(jobs) >= self.max_results:
                break
        if succeeded == 0 and failures:
            raise RuntimeError("Unstop requests failed: " + "; ".join(failures))
        if failures:
            logger.warning("Unstop partial fetch: %s", "; ".join(failures))
        return list(jobs.values())

    def _map(self, row: dict[str, Any]) -> Job | None:
        registration = mapping(row.get("regnRequirements"))
        if registration.get("reg_status") == "FINISHED":
            return None
        posted = date(row.get("updated_at")) or date(row.get("created_at"))
        if self.max_age_days is not None and posted is not None:
            if posted.astimezone(UTC) < datetime.now(UTC) - timedelta(days=self.max_age_days):
                return None
        detail = mapping(row.get("jobDetail"))
        mode = string(detail.get("type")).casefold()
        location = _location(row)
        description = plain_text(row.get("details"))
        skills = _names(row.get("required_skills"))
        if skills:
            description = " ".join(filter(None, (description, "Skills: " + ", ".join(skills))))
        remote = mode == "wfh" or (
            not mode and "work from home" in f"{location} {description}".casefold()
        )
        if mode in {"in_office", "hybrid"}:
            remote = False
        if remote:
            location = "Remote · India" if not location else f"Remote · {location}"
        disclosed = detail.get("show_salary") == 1 and not detail.get("not_disclosed")
        unpaid = detail.get("paid_unpaid") == "unpaid"
        salary_min = 0.0 if unpaid else number(detail.get("min_salary")) if disclosed else None
        salary_max = 0.0 if unpaid else number(detail.get("max_salary")) if disclosed else None
        currency = _CURRENCIES.get(string(detail.get("currency")).casefold()) if disclosed else None
        period = _PERIODS.get(string(detail.get("pay_in")).casefold()) if disclosed else None
        url = string(row.get("seo_url")) or string(row.get("public_url"))
        organization = mapping(row.get("organisation"))
        countries = {
            string(mapping(place).get("country")).casefold()
            for place in row.get("locations") or []
            if isinstance(place, dict) and mapping(place).get("country")
        }
        india_eligible = remote and (not countries or countries <= {"india", "in"})
        return Job(
            source=self.name,
            source_id=required(row.get("id"), "id"),
            title=required(row.get("title"), "title"),
            company=string(organization.get("name"))
            or string(row.get("organisation_name"))
            or "Unstop listing",
            location=location,
            description=description,
            apply_url=urljoin("https://unstop.com/", required(url, "URL")),
            posted_at=posted,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="INR" if unpaid else currency,
            salary_period="monthly" if unpaid else period,
            remote=remote,
            internship=True,
            india_eligible=india_eligible,
        )
