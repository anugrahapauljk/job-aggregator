"""Mocked public listing adapters."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from internship_bot.sources.internshala import InternshalaSource, parse_listing_page
from internship_bot.sources.linkedin import LinkedInSource

_CARD = """
<div class="individual_internship" internshipid="42" data-href="/internship/detail/backend-42">
  <span class="job-internship-name">Backend Development</span>
  <span class="company-name">Example Pvt Ltd</span>
  <span class="locations">Work from home</span>
  <span class="stipend">₹ 10,000 - 15,000 /month</span>
  <span class="status-info">2 days ago</span>
  <div class="about_job"><div class="text">Build Python APIs</div></div>
  <span class="job_skill">Python</span>
</div>
"""


def test_internshala_card_normalization() -> None:
    now = datetime(2026, 11, 21, tzinfo=UTC)
    jobs = parse_listing_page(_CARD, now)
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Development Internship"
    assert jobs[0].remote is True and jobs[0].india_eligible is True
    assert jobs[0].salary_min == 10000 and jobs[0].salary_max == 15000
    assert jobs[0].posted_at == datetime(2026, 11, 19, tzinfo=UTC)


@respx.mock
def test_internshala_pagination_and_dedup() -> None:
    route = respx.get(url__regex=r"https://internshala\.com/internships/.*").mock(
        return_value=httpx.Response(200, text=_CARD)
    )
    source = InternshalaSource(
        slugs=("work-from-home-backend-development-internships",),
        max_pages=2,
        request_delay_seconds=0,
        cache_ttl_minutes=0,
    )
    with httpx.Client() as client:
        jobs = source.fetch(client)
    assert route.call_count == 2  # A short page can still have a next page.
    assert len(jobs) == 1 and jobs[0].source == "internshala"


@respx.mock
def test_internshala_result_cap_samples_each_slug() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        slug = request.url.path.split("/")[2]
        card = _CARD.replace('internshipid="42"', f'internshipid="{slug}"')
        return httpx.Response(200, text=card)

    respx.get(url__regex=r"https://internshala\.com/internships/.*").mock(side_effect=response)
    source = InternshalaSource(
        slugs=("backend", "machine-learning"),
        max_pages=1,
        max_results=2,
        request_delay_seconds=0,
        cache_ttl_minutes=0,
    )
    with httpx.Client() as client:
        jobs = source.fetch(client)
    assert {job.source_id for job in jobs} == {"backend", "machine-learning"}


def test_linkedin_jobspy_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_scrape(term: str, results_wanted: int, hours_old: int) -> list[dict[str, Any]]:
        calls.append(term)
        return [
            {
                "id": "123",
                "title": "Backend Intern",
                "company": "Example",
                "location": "Remote - India",
                "description": "Remote Python internship",
                "job_url": "https://www.linkedin.com/jobs/view/123",
                "date_posted": datetime(2026, 11, 21, tzinfo=UTC),
                "is_remote": True,
            }
        ]

    monkeypatch.setattr("internship_bot.sources.linkedin._scrape", fake_scrape)
    source = LinkedInSource(
        search_terms=("backend intern",),
        request_delay_seconds=0,
        cache_ttl_minutes=60,
        cache_dir=tmp_path,
    )
    with httpx.Client() as client:
        first = source.fetch(client)
        second = source.fetch(client)
    assert calls == ["backend intern"]  # Cached on the second run.
    assert first[0].source_id == second[0].source_id == "123"
    assert first[0].remote is True and first[0].india_eligible is True
