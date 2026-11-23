"""Optional Adzuna India search API."""

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class AdzunaSource:
    app_id: str
    app_key: str
    max_results: int = 100
    name: str = "adzuna"
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        jobs: list[Job] = []
        page = 1
        while len(jobs) < self.max_results:
            response = client.get(
                f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                params={
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "results_per_page": min(50, self.max_results - len(jobs)),
                    "what": "intern remote",
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
            data = mapping(response.json())
            page_jobs = items(data.get("results"))
            for row in page_jobs:
                jobs.append(
                    Job(
                        source=self.name,
                        source_id=required(row.get("id"), "id"),
                        title=required(row.get("title"), "title"),
                        company=string(mapping(row.get("company")).get("display_name"))
                        or "Unknown company",
                        location=string(mapping(row.get("location")).get("display_name")),
                        description=plain_text(row.get("description")),
                        apply_url=required(row.get("redirect_url"), "URL"),
                        posted_at=date(row.get("created")),
                        salary_min=number(row.get("salary_min")),
                        salary_max=number(row.get("salary_max")),
                        salary_currency="INR" if row.get("salary_min") else None,
                        salary_period="annual" if row.get("salary_min") else None,
                        india_eligible=True,
                    )
                )
            if not page_jobs or len(page_jobs) < min(50, self.max_results - len(jobs)):
                break
            page += 1
        return jobs[: self.max_results]
