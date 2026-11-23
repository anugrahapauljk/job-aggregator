"""Public Internshala internship listing pages, using bounded HTML pagination."""

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from internship_bot.models import Job
from internship_bot.sources.http import get_text

logger = logging.getLogger(__name__)
_BASE = "https://internshala.com"
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
_STIPEND = re.compile(r"₹\s*([\d,]+)(?:\s*-\s*([\d,]+))?\s*/month", re.I)
_AGO = re.compile(r"(\d+)\s*(day|week|month)s?\s+ago", re.I)


def _text(card: Tag, selector: str) -> str:
    element = card.select_one(selector)
    return element.get_text(" ", strip=True) if element else ""


def _posted_at(text: str, now: datetime) -> datetime | None:
    match = _AGO.search(text)
    if match:
        days = {"day": 1, "week": 7, "month": 30}[match.group(2).casefold()]
        return now - timedelta(days=int(match.group(1)) * days)
    if text.casefold() in {"today", "just now"} or "hour" in text.casefold():
        return now
    return None


def parse_listing_page(html: str, now: datetime | None = None) -> list[Job]:
    """Parse one listing page; malformed cards are skipped individually."""
    now = now or datetime.now(UTC)
    jobs: list[Job] = []
    for card in BeautifulSoup(html, "html.parser").select(".individual_internship"):
        if not isinstance(card, Tag):
            continue
        title = _text(card, ".job-internship-name")
        company = _text(card, ".company-name")
        href = str(card.get("data-href") or "").strip()
        if not title or not company or not href:
            continue
        if "intern" not in title.casefold():
            title += " Internship"
        location = _text(card, ".locations")
        remote = location.casefold() == "work from home"
        if remote:
            location = "Remote · India"
        stipend = _text(card, ".stipend")
        match = _STIPEND.search(stipend)
        unpaid = stipend.casefold() == "unpaid"
        minimum = float(match.group(1).replace(",", "")) if match else 0.0 if unpaid else None
        maximum = (
            float((match.group(2) or match.group(1)).replace(",", ""))
            if match
            else 0.0
            if unpaid
            else None
        )
        skills = [element.get_text(" ", strip=True) for element in card.select(".job_skill")]
        description = _text(card, ".about_job .text")
        if skills:
            description = " ".join(filter(None, (description, "Skills: " + ", ".join(skills))))
        posted_label = _text(card, ".status-success, .status-info, .status-inactive")
        jobs.append(
            Job(
                source="internshala",
                source_id=str(card.get("internshipid") or href),
                title=title,
                company=company,
                location=location,
                description=description,
                apply_url=urljoin(_BASE, href),
                posted_at=_posted_at(posted_label, now),
                salary_min=minimum,
                salary_max=maximum,
                salary_currency="INR" if minimum is not None else None,
                salary_period="monthly" if minimum is not None else None,
                remote=remote,
                internship=True,
                india_eligible=True if remote else None,
            )
        )
    return jobs


@dataclass(frozen=True, slots=True)
class InternshalaSource:
    slugs: tuple[str, ...]
    max_pages: int = 2
    max_results: int = 100
    request_delay_seconds: float = 1.0
    cache_ttl_minutes: int = 60
    cache_dir: Path | None = None
    name: str = "internshala"
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        batches: list[list[Job]] = []
        failures: list[str] = []
        succeeded = 0
        last_request = 0.0
        for slug in self.slugs:
            batch: list[Job] = []
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                failures.append(f"invalid filter slug: {slug}")
                continue
            for page in range(1, self.max_pages + 1):
                if last_request:
                    time.sleep(
                        max(0.0, self.request_delay_seconds - (time.monotonic() - last_request))
                    )
                path = f"/internships/{slug}/" if page == 1 else f"/internships/{slug}/page-{page}/"
                try:
                    html = get_text(
                        client,
                        _BASE + path,
                        cache_dir=self.cache_dir,
                        cache_ttl_minutes=self.cache_ttl_minutes,
                        headers={"User-Agent": _BROWSER_UA},
                    )
                except (httpx.HTTPError, OSError) as exc:
                    failures.append(f"{slug} page {page}: {exc}")
                    break
                last_request = time.monotonic()
                cards = parse_listing_page(html)
                if not cards:
                    if page == 1:
                        failures.append(f"{slug}: no listing cards found")
                    break
                succeeded += 1
                batch.extend(cards)
            batches.append(batch)
        if succeeded == 0:
            raise RuntimeError("Internshala fetch failed: " + "; ".join(failures or ["no slugs"]))
        if failures:
            logger.warning("Internshala partial fetch: %s", "; ".join(failures))
        jobs: dict[str, Job] = {}
        for index in range(max(map(len, batches), default=0)):
            for batch in batches:
                if index < len(batch):
                    job = batch[index]
                    jobs[job.source_id] = job
                    if len(jobs) >= self.max_results:
                        return list(jobs.values())
        return list(jobs.values())
