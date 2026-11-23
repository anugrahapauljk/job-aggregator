"""Daily cached reference FX rates, with approximate outage fallbacks."""

import logging
import sqlite3
from datetime import UTC, datetime

import httpx

from internship_bot.models import Job
from internship_bot.sources.http import get_json

logger = logging.getLogger(__name__)
_FALLBACK_INR = {
    "USD": 94.1,
    "EUR": 104.02,
    "GBP": 124.62,
    "CAD": 68.0,
    "AUD": 63.0,
    "SGD": 73.0,
    "JPY": 0.59,
}


def load_inr_rates(
    jobs: list[Job],
    client: httpx.Client,
    connection: sqlite3.Connection,
    now: datetime | None = None,
) -> dict[str, float]:
    """Fetch each needed currency once per UTC day; use cached or fallback rates on failure."""
    today = (now or datetime.now(UTC)).date().isoformat()
    currencies = {
        job.salary_currency.upper()
        for job in jobs
        if job.salary_currency and (job.salary_min is not None or job.salary_max is not None)
    } - {"INR"}
    rates: dict[str, float] = {}
    for currency in sorted(currencies):
        cached = connection.execute(
            "SELECT inr_rate, fetched_on FROM fx_rates WHERE currency = ?", (currency,)
        ).fetchone()
        if cached and cached[1] == today:
            rates[currency] = float(cached[0])
            continue
        try:
            payload = get_json(
                client,
                f"https://api.frankfurter.dev/v2/rate/{currency.lower()}/inr",
                {},
            )
            rate = float(payload["rate"])
            if rate <= 0:
                raise ValueError("non-positive exchange rate")
            source = "frankfurter"
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            if cached:
                rate = float(cached[0])
                source = "cached"
            elif currency in _FALLBACK_INR:
                rate = _FALLBACK_INR[currency]
                source = "fallback"
            else:
                logger.warning("FX unavailable for %s; stipend left unstated: %s", currency, exc)
                continue
            logger.warning("FX unavailable for %s; using %s INR rate: %s", currency, source, exc)
        rates[currency] = rate
        connection.execute(
            """INSERT INTO fx_rates (currency, inr_rate, fetched_on, rate_source)
            VALUES (?, ?, ?, ?) ON CONFLICT(currency) DO UPDATE SET
            inr_rate = excluded.inr_rate, fetched_on = excluded.fetched_on,
            rate_source = excluded.rate_source""",
            (currency, rate, today, source),
        )
    return rates
