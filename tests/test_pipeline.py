"""Cross-source filtering and near-duplicate handling."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from internship_bot.config import load_config
from internship_bot.models import Job
from internship_bot.pipeline import group_jobs, normalize, select_jobs


def test_filters_and_deduplicates_across_sources() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    base = Job(
        source="unstop",
        source_id="1",
        title="ML Intern",
        company="Acme Pvt Ltd",
        location="Remote India",
        description="Machine learning with Python",
        apply_url="https://unstop.com/one",
        posted_at=datetime.now(UTC),
        remote=True,
        india_eligible=True,
    )
    jobs = [
        base,
        replace(
            base,
            source="greenhouse",
            source_id="2",
            title="Machine Learning Intern",
            company="Acme Technologies",
            apply_url="https://example.com/two",
        ),
        replace(base, source_id="3", title="ML Engineer", apply_url="https://example.com/three"),
        replace(
            base,
            source_id="4",
            location="On-site India",
            remote=False,
            apply_url="https://example.com/four",
        ),
        replace(
            base,
            source_id="5",
            posted_at=datetime.now(UTC) - timedelta(days=60),
            apply_url="https://example.com/five",
        ),
    ]
    assert [(job.source, job.source_id) for job in select_jobs(jobs, config)] == [("unstop", "1")]


def test_aliases_pay_floor_and_scoring() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml").model_copy(
        update={"min_stipend_inr_per_month": 10000, "include_keywords": ["Python"]}
    )
    now = datetime(2026, 11, 23, tzinfo=UTC)
    base = Job(
        source="internshala",
        source_id="one",
        title="ML Intern",
        company="Acme Pvt Ltd",
        location="Remote India",
        description="Python and machine learning",
        apply_url="https://example.com/one",
        posted_at=now,
        remote=True,
        india_eligible=True,
    )
    alias = replace(
        base,
        source="linkedin",
        source_id="two",
        title="Machine Learning Intern (Remote)",
        company="Acme Technologies",
    )
    low_paid = replace(
        base,
        source_id="three",
        company="Other",
        salary_min=5000,
        salary_currency="INR",
        salary_period="monthly",
    )
    paid = replace(
        base,
        source_id="four",
        company="Another",
        salary_min=15000,
        salary_currency="INR",
        salary_period="monthly",
    )
    groups = group_jobs([base, alias, low_paid, paid], config, now)
    assert len(groups) == 2
    assert groups[0].primary.company == "Another"  # Stated stipend boosts ranking.
    assert {(job.source, job.source_id) for job in groups[1].listings} == {
        ("internshala", "one"),
        ("linkedin", "two"),
    }
    assert groups[1].primary.stipend_inr_per_month is None  # Unknown pay stays eligible.


def test_remote_and_india_require_text_evidence() -> None:
    base = Job(
        source="example",
        source_id="1",
        title="Backend Intern",
        company="Example",
        location="India",
        description="Build APIs in the office",
        apply_url="https://example.com",
        remote=True,
    )
    assert normalize(base).remote is False
    worldwide = replace(base, location="Remote Worldwide", description="Build APIs")
    assert normalize(worldwide).remote is True
    assert normalize(worldwide).india_eligible is True


def test_experience_filter_reads_requirements_only() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml").model_copy(
        update={"max_experience_years": 2}
    )
    base = Job(
        source="example",
        source_id="1",
        title="Backend Intern",
        company="Example",
        location="Remote India",
        description=" ".join(
            ("About us: 10 years of experience.", "Requirements: 1 year of experience with Python.")
        ),
        apply_url="https://example.com",
        remote=True,
        india_eligible=True,
    )
    assert select_jobs([base], config)
    too_senior = replace(base, description="Requirements: 3+ years of experience with Python.")
    assert not select_jobs([too_senior], config)
    no_requirement_section = replace(base, description="Our company has 10 years of experience.")
    assert select_jobs([no_requirement_section], config)
