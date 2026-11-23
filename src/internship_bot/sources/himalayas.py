"""Himalayas public remote jobs API."""

from dataclasses import dataclass

import httpx

from internship_bot.models import Job
from internship_bot.sources.parsing import date, items, number, plain_text, required, string


@dataclass(frozen=True, slots=True)
class HimalayasSource:
    max_results: int = 100
    name: str = "himalayas"
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        jobs: list[Job] = []
        cursor: str | None = None
        while len(jobs) < self.max_results:
            params: dict[str, str | int] = {"limit": min(20, self.max_results - len(jobs))}
            if cursor:
                params["cursor"] = cursor
            response = client.get("https://himalayas.app/jobs/api", params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Himalayas returned an invalid response")
            page = items(data.get("jobs"))
            for row in page:
                restrictions = row.get("locationRestrictions")
                if isinstance(restrictions, list):
                    labels = [string(item) for item in restrictions]
                    eligible = not labels or any(
                        label.casefold() in {"india", "in"} for label in labels
                    )
                    location = "Remote · " + (", ".join(labels) if labels else "Worldwide")
                else:
                    eligible = None
                    location = "Remote"
                jobs.append(
                    Job(
                        source=self.name,
                        source_id=required(row.get("guid"), "guid"),
                        title=required(row.get("title"), "title"),
                        company=required(row.get("companyName"), "company"),
                        location=location,
                        description=plain_text(row.get("description") or row.get("excerpt")),
                        apply_url=required(row.get("applicationLink") or row.get("guid"), "URL"),
                        posted_at=date(row.get("pubDate")),
                        salary_min=number(row.get("minSalary")),
                        salary_max=number(row.get("maxSalary")),
                        salary_currency=string(row.get("currency")) or None,
                        salary_period=string(row.get("salaryPeriod")) or None,
                        remote=True,
                        india_eligible=eligible,
                    )
                )
            cursor = string(data.get("nextCursor")) or None
            if not cursor or not page:
                break
        return jobs[: self.max_results]
