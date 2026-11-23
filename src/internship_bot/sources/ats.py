"""Public per-company ATS board adapters."""

from dataclasses import dataclass
from typing import Any

import httpx

from internship_bot.models import Job
from internship_bot.sources.parsing import (
    date,
    items,
    mapping,
    number,
    plain_text,
    required,
    string,
)


def _slug(value: str) -> str:
    if not value or not all(character.isalnum() or character in "-_" for character in value):
        raise ValueError(f"invalid ATS company slug: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class GreenhouseSource:
    slug: str
    complete_inventory: bool = True

    @property
    def name(self) -> str:
        return f"greenhouse:{self.slug}"

    def fetch(self, client: httpx.Client) -> list[Job]:
        response = client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{_slug(self.slug)}/jobs",
            params={"content": "true"},
        )
        response.raise_for_status()
        data = mapping(response.json())
        return [
            Job(
                source=self.name,
                source_id=required(row.get("id"), "id"),
                title=required(row.get("title"), "title"),
                company=self.slug,
                location=string(mapping(row.get("location")).get("name")),
                description=plain_text(row.get("content")),
                apply_url=required(row.get("absolute_url"), "URL"),
                posted_at=date(row.get("first_published") or row.get("updated_at")),
            )
            for row in items(data.get("jobs"))
        ]


@dataclass(frozen=True, slots=True)
class LeverSource:
    slug: str
    complete_inventory: bool = True

    @property
    def name(self) -> str:
        return f"lever:{self.slug}"

    def fetch(self, client: httpx.Client) -> list[Job]:
        jobs: list[Job] = []
        offset = 0
        while True:
            response = client.get(
                f"https://api.lever.co/v0/postings/{_slug(self.slug)}",
                params={"mode": "json", "skip": offset, "limit": 100},
            )
            response.raise_for_status()
            page = items(response.json())
            for row in page:
                categories = mapping(row.get("categories"))
                salary = mapping(row.get("salaryRange"))
                jobs.append(
                    Job(
                        source=self.name,
                        source_id=required(row.get("id"), "id"),
                        title=required(row.get("text"), "title"),
                        company=self.slug,
                        location=string(categories.get("location")),
                        description=plain_text(
                            row.get("descriptionPlain") or row.get("description")
                        ),
                        apply_url=required(row.get("applyUrl") or row.get("hostedUrl"), "URL"),
                        posted_at=date(row.get("createdAt")),
                        salary_min=number(salary.get("min")),
                        salary_max=number(salary.get("max")),
                        salary_currency=string(salary.get("currency")) or None,
                        salary_period=string(salary.get("interval")) or None,
                        remote=string(row.get("workplaceType")).casefold() == "remote",
                    )
                )
            if len(page) < 100:
                break
            offset += len(page)
        return jobs


@dataclass(frozen=True, slots=True)
class AshbySource:
    slug: str
    complete_inventory: bool = True

    @property
    def name(self) -> str:
        return f"ashby:{self.slug}"

    def fetch(self, client: httpx.Client) -> list[Job]:
        response = client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{_slug(self.slug)}",
            params={"includeCompensation": "true"},
        )
        response.raise_for_status()
        data = mapping(response.json())
        jobs: list[Job] = []
        for row in items(data.get("jobs")):
            components = mapping(row.get("compensation")).get("summaryComponents")
            salary = next(
                (
                    component
                    for component in items(components or [])
                    if component.get("compensationType") == "Salary"
                ),
                {},
            )
            jobs.append(
                Job(
                    source=self.name,
                    source_id=required(row.get("id") or row.get("jobUrl"), "id or URL"),
                    title=required(row.get("title"), "title"),
                    company=self.slug,
                    location=string(row.get("location")),
                    description=plain_text(
                        row.get("descriptionPlain") or row.get("descriptionHtml")
                    ),
                    apply_url=required(row.get("applyUrl") or row.get("jobUrl"), "URL"),
                    posted_at=date(row.get("publishedAt")),
                    salary_min=number(salary.get("minValue")),
                    salary_max=number(salary.get("maxValue")),
                    salary_currency=string(salary.get("currencyCode")) or None,
                    salary_period=string(salary.get("interval")) or None,
                    remote=string(row.get("workplaceType")).casefold() == "remote",
                )
            )
        return jobs


def _smartrecruiters_description(data: dict[str, Any]) -> str:
    sections = mapping(mapping(data.get("jobAd")).get("sections"))
    return " ".join(
        plain_text(mapping(sections.get(name)).get("text"))
        for name in ("jobDescription", "qualifications", "additionalInformation")
    ).strip()


@dataclass(frozen=True, slots=True)
class SmartRecruitersSource:
    slug: str
    complete_inventory: bool = True

    @property
    def name(self) -> str:
        return f"smartrecruiters:{self.slug}"

    def fetch(self, client: httpx.Client) -> list[Job]:
        jobs: list[Job] = []
        offset = 0
        base = f"https://api.smartrecruiters.com/v1/companies/{_slug(self.slug)}/postings"
        while True:
            response = client.get(base, params={"limit": 100, "offset": offset})
            response.raise_for_status()
            data = mapping(response.json())
            page = items(data.get("content"))
            for row in page:
                job_id = required(row.get("id"), "id")
                title = required(row.get("name"), "title")
                details: dict[str, Any] = {}
                if any(term in title.casefold() for term in ("intern", "trainee")):
                    detail_response = client.get(f"{base}/{job_id}")
                    detail_response.raise_for_status()
                    details = mapping(detail_response.json())
                location = mapping(row.get("location"))
                place = ", ".join(
                    string(location.get(field))
                    for field in ("city", "country")
                    if location.get(field)
                )
                jobs.append(
                    Job(
                        source=self.name,
                        source_id=job_id,
                        title=title,
                        company=string(mapping(row.get("company")).get("name")) or self.slug,
                        location=place,
                        description=_smartrecruiters_description(details),
                        apply_url=string(details.get("applyUrl"))
                        or f"https://jobs.smartrecruiters.com/{self.slug}/{job_id}",
                        posted_at=date(row.get("releasedDate")),
                        remote=location.get("remote") is True,
                        india_eligible=True
                        if string(location.get("country")).casefold() in {"in", "india"}
                        else None,
                    )
                )
            offset += len(page)
            if not page or offset >= int(data.get("totalFound", offset)):
                break
        return jobs
