"""Remote OK public JSON feed."""

from dataclasses import dataclass

import httpx

from internship_bot.models import Job
from internship_bot.sources.parsing import date, items, number, plain_text, required, string


@dataclass(frozen=True, slots=True)
class RemoteOkSource:
    name: str = "remoteok"
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        response = client.get("https://remoteok.com/api")
        response.raise_for_status()
        jobs: list[Job] = []
        for row in items(response.json()):
            if not row.get("id"):
                continue  # Feed's first item is attribution metadata.
            location = string(row.get("location")) or "Remote"
            jobs.append(
                Job(
                    source=self.name,
                    source_id=required(row.get("id"), "id"),
                    title=required(row.get("position"), "title"),
                    company=required(row.get("company"), "company"),
                    location=location,
                    description=plain_text(row.get("description")),
                    apply_url=required(row.get("url"), "URL"),
                    posted_at=date(row.get("date") or row.get("epoch")),
                    salary_min=number(row.get("salary_min")),
                    salary_max=number(row.get("salary_max")),
                    salary_currency="USD" if row.get("salary_min") else None,
                    salary_period="annual" if row.get("salary_min") else None,
                    remote=True,
                    india_eligible=None,
                )
            )
        return jobs
