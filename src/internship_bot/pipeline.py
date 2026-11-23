"""Normalize, filter, score, and group source-neutral internship listings."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from rapidfuzz import fuzz

from internship_bot.config import AppConfig
from internship_bot.models import Job

_COMPANY_SUFFIX = re.compile(
    r"\b(?:pvt|private|ltd|limited|inc|incorporated|technologies|technology|corp|corporation)\b",
    re.I,
)
_INTERN = re.compile(r"\b(?:intern|internship|trainee)\b", re.I)
_REMOTE = re.compile(r"\b(?:remote|work from home|wfh|anywhere)\b", re.I)
_NEGATIVE_REMOTE = re.compile(
    r"\b(?:no remote|not remote|non.remote|on.site only|in.office|hybrid)\b", re.I
)
_TITLE_NOISE = re.compile(r"\b(?:remote|wfh|work from home)\b", re.I)
_INDIA_OR_GLOBAL = re.compile(r"\b(?:india|worldwide|anywhere|global)\b", re.I)
_REQUIREMENTS = re.compile(
    r"\b(?:requirements|qualifications|who can apply|eligibility)\s*[:\-]", re.I
)
_NEXT_SECTION = re.compile(
    r"\b(?:about us|about the company|benefits|perks|responsibilities|how to apply)\s*[:\-]",
    re.I,
)
_YEARS_REQUIRED = re.compile(
    r"\b(\d+)\s*(?:\+|[-–]\s*\d+)?\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b", re.I
)


@dataclass(frozen=True, slots=True)
class JobGroup:
    primary: Job
    listings: tuple[Job, ...]
    canonical_key: str
    score: float


def _words(text: str) -> str:
    expanded = re.sub(r"\bml\b", "machine learning", text.casefold())
    expanded = re.sub(r"\bsde\b", "software development engineer", expanded)
    return " ".join(re.findall(r"[a-z0-9]+", expanded))


def company_key(company: str) -> str:
    return _words(_COMPANY_SUFFIX.sub(" ", company))


def title_key(title: str) -> str:
    return _words(_TITLE_NOISE.sub(" ", title))


def location_key(location: str) -> str:
    normalized = location.casefold().replace("work from home", "remote").replace("wfh", "remote")
    return _words(normalized)


def canonical_key(job: Job) -> str:
    parts = (company_key(job.company), title_key(job.title), location_key(job.location))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def same_job(left: Job, right: Job, threshold: int) -> bool:
    if company_key(left.company) != company_key(right.company):
        return False
    if canonical_key(left) == canonical_key(right):
        return True
    return (
        left.remote == right.remote
        and fuzz.token_sort_ratio(title_key(left.title), title_key(right.title)) >= threshold
    )


def normalize(job: Job, inr_rates: Mapping[str, float] | None = None) -> Job:
    title = " ".join(job.title.split())
    location = " ".join(job.location.split())
    description = " ".join(job.description.split())
    remote_text = f"{location} {description}"
    remote = bool(_REMOTE.search(remote_text)) and not bool(_NEGATIVE_REMOTE.search(remote_text))
    india_eligible = job.india_eligible
    if india_eligible is None and remote and _INDIA_OR_GLOBAL.search(location):
        india_eligible = True
    stipend = job.stipend_inr_per_month
    if stipend is None and job.salary_currency:
        pay = job.salary_min if job.salary_min is not None else job.salary_max
        period = (job.salary_period or "").casefold()
        multiplier = {
            "hour": 40 * 52 / 12,
            "hourly": 40 * 52 / 12,
            "day": 5 * 52 / 12,
            "daily": 5 * 52 / 12,
            "week": 52 / 12,
            "weekly": 52 / 12,
            "month": 1,
            "monthly": 1,
            "year": 1 / 12,
            "yearly": 1 / 12,
            "annual": 1 / 12,
            "annually": 1 / 12,
        }.get(period)
        currency = job.salary_currency.upper()
        rate = 1.0 if currency == "INR" else (inr_rates or {}).get(currency)
        if pay is not None and multiplier is not None and rate is not None:
            stipend = round(pay * multiplier * rate, 2)
    return replace(
        job,
        title=title,
        company=" ".join(job.company.split()),
        location=location,
        description=description,
        remote=remote,
        internship=bool(_INTERN.search(title)),
        india_eligible=india_eligible,
        stipend_inr_per_month=stipend,
    )


def _contains(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", text.casefold()))


def _required_experience_years(description: str) -> int | None:
    heading = _REQUIREMENTS.search(description)
    if heading is None:
        return None
    tail = description[heading.end() :]
    next_section = _NEXT_SECTION.search(tail)
    requirements = tail[: next_section.start()] if next_section else tail
    values = [int(match.group(1)) for match in _YEARS_REQUIRED.finditer(requirements)]
    return min(values) if values else None


def _passes(job: Job, config: AppConfig, now: datetime) -> bool:
    if config.must_be_remote and not job.remote:
        return False
    if config.must_be_internship and not job.internship:
        return False
    if config.require_india_eligibility and job.india_eligible is not True:
        return False
    if config.sources.max_posting_age_days is not None and job.posted_at is not None:
        if job.posted_at.astimezone(UTC) < now - timedelta(
            days=config.sources.max_posting_age_days
        ):
            return False
    searchable = f"{job.title} {job.description}"
    if config.include_keywords and not any(
        _contains(searchable, term) for term in config.include_keywords
    ):
        return False
    if any(_contains(searchable, term) for term in config.exclude_keywords):
        return False
    if config.max_experience_years:
        required = _required_experience_years(job.description)
        if required is not None and required > config.max_experience_years:
            return False
    floor = config.min_stipend_inr_per_month
    if floor is not None and job.stipend_inr_per_month is not None:
        if job.stipend_inr_per_month < floor:
            return False
    return True


def score_job(job: Job, config: AppConfig, now: datetime) -> float:
    """Favor role matches in the title, then pay transparency and recency."""
    title_match = max(
        (len(role.split()) for role in config.target_roles if _contains(job.title, role)), default=0
    )
    description_match = any(_contains(job.description, role) for role in config.target_roles)
    score = float(title_match * 3 + (1 if description_match else 0))
    if job.stipend_inr_per_month is not None and job.stipend_inr_per_month > 0:
        score += 2
    if job.posted_at is not None:
        age_days = max(0.0, (now - job.posted_at.astimezone(UTC)).total_seconds() / 86400)
        score += max(0.0, 3.0 - age_days / 7)
    return round(score, 3)


def group_jobs(
    jobs: list[Job],
    config: AppConfig,
    now: datetime | None = None,
    inr_rates: Mapping[str, float] | None = None,
) -> list[JobGroup]:
    now = now or datetime.now(UTC)
    grouped: list[list[Job]] = []
    by_company: dict[str, list[int]] = {}
    for raw in jobs:
        job = normalize(raw, inr_rates)
        if not _passes(job, config, now):
            continue
        company = company_key(job.company)
        match = next(
            (
                index
                for index in by_company.get(company, [])
                if any(
                    same_job(job, member, config.fuzzy_title_threshold) for member in grouped[index]
                )
            ),
            None,
        )
        if match is None:
            by_company.setdefault(company, []).append(len(grouped))
            grouped.append([job])
        elif all(
            (member.source, member.source_id) != (job.source, job.source_id)
            for member in grouped[match]
        ):
            grouped[match].append(job)
    result = [
        JobGroup(
            primary=members[0],
            listings=tuple(members),
            canonical_key=canonical_key(members[0]),
            score=max(score_job(member, config, now) for member in members),
        )
        for members in grouped
    ]
    return sorted(result, key=lambda group: (-group.score, group.primary.title.casefold()))


def select_jobs(jobs: list[Job], config: AppConfig, now: datetime | None = None) -> list[Job]:
    """Return ranked representatives for CLI previews and later digests."""
    return [group.primary for group in group_jobs(jobs, config, now)]
