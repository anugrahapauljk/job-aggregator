"""Source-neutral job record and lifecycle types."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    description: str
    apply_url: str
    posted_at: datetime | None = None
    stipend_inr_per_month: float | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    remote: bool = False
    internship: bool = False
    india_eligible: bool | None = None
