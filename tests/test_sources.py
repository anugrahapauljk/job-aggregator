"""Public source response parsing and isolation with mocked HTTP."""

from pathlib import Path

import httpx
import pytest
import respx

from internship_bot.sources.adzuna import AdzunaSource
from internship_bot.sources.ats import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    SmartRecruitersSource,
)
from internship_bot.sources.base import DisabledSource
from internship_bot.sources.himalayas import HimalayasSource
from internship_bot.sources.remoteok import RemoteOkSource
from internship_bot.sources.runner import fetch_all
from internship_bot.sources.unstop import UnstopSource
from internship_bot.storage import database, initialize_database


@respx.mock
def test_remoteok_and_himalayas() -> None:
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"legal": "Feed attribution"},
                {
                    "id": "r1",
                    "position": "Backend Intern",
                    "company": "Example",
                    "location": "Worldwide",
                    "url": "https://remoteok.com/remote-jobs/r1",
                    "description": "<p>Python</p>",
                },
            ],
        )
    )
    respx.get(url__regex=r"https://himalayas\.app/jobs/api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "guid": "https://himalayas.app/jobs/one",
                        "title": "ML Intern",
                        "companyName": "Example",
                        "locationRestrictions": ["India"],
                        "description": "<p>Work from anywhere in India</p>",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        remoteok = RemoteOkSource().fetch(client)
        himalayas = HimalayasSource().fetch(client)
    assert len(remoteok) == 1
    assert remoteok[0].description == "Python"
    assert himalayas[0].india_eligible is True
    assert himalayas[0].location == "Remote · India"


@respx.mock
def test_company_boards() -> None:
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 11,
                        "title": "Python Intern",
                        "location": {"name": "Remote - India"},
                        "content": "<p>Build APIs</p>",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/11",
                    }
                ]
            },
        )
    )
    respx.get(url__regex=r"https://api\.lever\.co/.*").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "lev-1",
                    "text": "Backend Intern",
                    "categories": {"location": "Remote"},
                    "descriptionPlain": "Build services",
                    "applyUrl": "https://jobs.lever.co/acme/lev-1/apply",
                    "workplaceType": "remote",
                    "createdAt": 1_700_000_000_000,
                }
            ],
        )
    )
    respx.get(url__regex=r"https://api\.ashbyhq\.com/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Systems Intern",
                        "location": "India",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/one",
                        "descriptionPlain": "Build infrastructure",
                        "workplaceType": "Remote",
                    }
                ]
            },
        )
    )
    respx.get(url__regex=r"https://api\.smartrecruiters\.com/.*/postings\?.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {
                        "id": "sr-1",
                        "name": "Data Intern",
                        "company": {"name": "Acme"},
                        "location": {"country": "IN", "remote": True},
                    }
                ],
                "totalFound": 1,
            },
        )
    )
    respx.get("https://api.smartrecruiters.com/v1/companies/acme/postings/sr-1").mock(
        return_value=httpx.Response(
            200,
            json={"jobAd": {"sections": {"jobDescription": {"text": "<p>SQL</p>"}}}},
        )
    )
    with httpx.Client() as client:
        greenhouse = GreenhouseSource("acme").fetch(client)
        lever = LeverSource("acme").fetch(client)
        ashby = AshbySource("acme").fetch(client)
        smartrecruiters = SmartRecruitersSource("acme").fetch(client)
    assert greenhouse[0].description == "Build APIs"
    assert lever[0].posted_at is not None and lever[0].posted_at.year == 2023
    assert ashby[0].remote is True
    assert smartrecruiters[0].description == "SQL"


@respx.mock
def test_unstop_and_adzuna() -> None:
    respx.get(url__regex=r"https://unstop\.com/api/public/opportunity/search-result.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "data": [
                        {
                            "id": 7,
                            "title": "Backend Intern",
                            "organisation": {"name": "Example"},
                            "location": "Work from Home",
                            "seo_url": "/internships/backend-intern-7",
                        }
                    ],
                    "last_page": 1,
                }
            },
        )
    )
    respx.get(url__regex=r"https://api\.adzuna\.com/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "ad-1",
                        "title": "Software Intern Remote",
                        "company": {"display_name": "Example"},
                        "location": {"display_name": "India"},
                        "redirect_url": "https://www.adzuna.in/jobs/one",
                        "salary_min": 120000,
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        unstop = UnstopSource().fetch(client)
        adzuna = AdzunaSource("id", "key").fetch(client)
    assert unstop[0].remote is True
    assert unstop[0].apply_url == "https://unstop.com/internships/backend-intern-7"
    assert adzuna[0].salary_currency == "INR"


@respx.mock
def test_unstop_search_pagination_and_work_mode() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        row = {
            "id": page,
            "title": "Backend Intern",
            "organisation": {"name": "Example"},
            "seo_url": f"https://unstop.com/internships/job-{page}",
            "jobDetail": {
                "type": "wfh" if page == 1 else "in_office",
                "show_salary": 1,
                "min_salary": 15000,
                "pay_in": "monthly",
                "currency": "fa-rupee",
            },
            "updated_at": "2026-11-21T00:00:00+05:30",
            "regnRequirements": {"reg_status": "STARTED"},
        }
        return httpx.Response(200, json={"data": {"data": [row], "last_page": 2}})

    route = respx.get("https://unstop.com/api/public/opportunity/search-result").mock(
        side_effect=response
    )
    with httpx.Client() as client:
        jobs = UnstopSource(
            search_terms=("backend",),
            max_pages=2,
            max_age_days=None,
            request_delay_seconds=0,
            cache_ttl_minutes=0,
        ).fetch(client)
    assert route.call_count == 2
    assert [job.remote for job in jobs] == [True, False]
    assert jobs[0].salary_min == 15000
    assert jobs[0].apply_url.endswith("job-1")


@respx.mock
def test_failure_isolated_and_recorded(tmp_path: Path) -> None:
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(503))
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        connection.execute(
            """INSERT INTO jobs (
                canonical_key, title, company, location, apply_url, remote, internship,
                first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "existing",
                "Backend Intern",
                "Example",
                "Remote India",
                "https://example.com/apply",
                1,
                1,
                "2026-11-20T00:00:00Z",
                "2026-11-20T00:00:00Z",
            ),
        )
    with httpx.Client() as client, database(path) as connection:
        results = fetch_all(
            [RemoteOkSource(), DisabledSource("internshala", "blocked")], client, connection
        )
    assert [result.status for result in results] == ["failed", "skipped"]
    with database(path) as connection:
        stored = connection.execute("SELECT source, status FROM source_runs ORDER BY id").fetchall()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE canonical_key = 'existing'"
        ).fetchone()
    assert stored == [("remoteok", "failed"), ("internshala", "skipped")]
    assert job_status == ("open",)


@respx.mock
def test_runner_retries_transient_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("internship_bot.sources.runner.time.sleep", sleeps.append)
    route = respx.get("https://remoteok.com/api").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=[]),
        ]
    )
    with httpx.Client() as client:
        results = fetch_all([RemoteOkSource()], client)
    assert route.call_count == 2
    assert sleeps == [0.0]
    assert results[0].status == "success"
