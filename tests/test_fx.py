"""Currency lookup, cache, fallback, and monthly conversion."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from internship_bot.fx import load_inr_rates
from internship_bot.models import Job
from internship_bot.pipeline import normalize
from internship_bot.storage import database, initialize_database


def _job(currency: str = "USD") -> Job:
    return Job(
        source="board",
        source_id="one",
        title="Backend Intern",
        company="Example",
        location="Remote India",
        description="Python",
        apply_url="https://example.com",
        salary_min=1200,
        salary_currency=currency,
        salary_period="yearly",
    )


@respx.mock
def test_daily_fx_cache_and_monthly_conversion(tmp_path: Path) -> None:
    route = respx.get("https://api.frankfurter.dev/v2/rate/usd/inr").mock(
        return_value=httpx.Response(200, json={"rate": 90.0})
    )
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    today = datetime(2026, 11, 23, tzinfo=UTC)
    with httpx.Client() as client, database(path) as connection:
        rates = load_inr_rates([_job()], client, connection, today)
        assert load_inr_rates([_job()], client, connection, today) == rates
    assert route.call_count == 1
    assert normalize(_job(), rates).stipend_inr_per_month == 9000.0


@respx.mock
def test_fx_failure_uses_last_cached_rate(tmp_path: Path) -> None:
    respx.get("https://api.frankfurter.dev/v2/rate/usd/inr").mock(return_value=httpx.Response(503))
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    today = datetime(2026, 11, 23, tzinfo=UTC)
    with httpx.Client() as client, database(path) as connection:
        connection.execute("INSERT INTO fx_rates VALUES ('USD', 88, '2026-11-22', 'frankfurter')")
        assert load_inr_rates([_job()], client, connection, today) == {"USD": 88.0}


@respx.mock
def test_fx_fallback_and_unknown_currency(tmp_path: Path) -> None:
    respx.get("https://api.frankfurter.dev/v2/rate/usd/inr").mock(return_value=httpx.Response(503))
    respx.get("https://api.frankfurter.dev/v2/rate/zzz/inr").mock(return_value=httpx.Response(404))
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with httpx.Client() as client, database(path) as connection:
        rates = load_inr_rates([_job(), _job("ZZZ")], client, connection)
    assert rates["USD"] > 0 and "ZZZ" not in rates
    assert normalize(_job("ZZZ"), rates).stipend_inr_per_month is None
    weekly = normalize(replace(_job(), salary_period="weekly"), {"USD": 90})
    assert weekly.stipend_inr_per_month == round(1200 * 52 / 12 * 90, 2)
