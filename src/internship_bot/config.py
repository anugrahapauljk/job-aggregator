"""Validated, user-editable application settings."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AtsCompanies(StrictModel):
    greenhouse: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    ashby: list[str] = Field(default_factory=list)
    smartrecruiters: list[str] = Field(default_factory=list)


class EmailSettings(StrictModel):
    recipient: str
    max_jobs_per_digest: int = Field(default=20, ge=1, le=100)
    send_no_new_jobs: bool = False

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        # Keep validation local; no network/DNS lookup is needed for configuration.
        value = value.strip()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[1]:
            raise ValueError("recipient must be an email address")
        return value


class ResumeSettings(StrictModel):
    enabled: bool = False
    provider: str | None = None


class SourceSettings(StrictModel):
    max_results_per_source: int = Field(default=100, ge=1, le=500)
    unstop_search_terms: list[str] = Field(default_factory=list)
    unstop_max_pages: int = Field(default=3, ge=1, le=20)
    max_posting_age_days: int | None = Field(default=30, ge=1)
    request_delay_seconds: float = Field(default=1.0, ge=0)
    cache_ttl_minutes: int = Field(default=60, ge=0)
    linkedin_enabled: bool = True
    linkedin_search_terms: list[str] = Field(default_factory=list)
    linkedin_results_per_query: int = Field(default=10, ge=1, le=50)
    linkedin_hours_old: int = Field(default=168, ge=1)
    internshala_enabled: bool = True
    internshala_slugs: list[str] = Field(default_factory=list)
    internshala_max_pages: int = Field(default=2, ge=1, le=10)

    @field_validator("unstop_search_terms", "linkedin_search_terms", "internshala_slugs")
    @classmethod
    def normalize_search_terms(cls, values: list[str]) -> list[str]:
        terms = [value.strip() for value in values]
        if any(not value for value in terms):
            raise ValueError("search terms cannot be blank")
        return terms


class AppConfig(StrictModel):
    target_roles: list[str] = Field(min_length=1)
    must_be_remote: bool = True
    must_be_internship: bool = True
    require_india_eligibility: bool = True
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    min_stipend_inr_per_month: float | None = Field(default=None, ge=0)
    max_experience_years: int = Field(default=0, ge=0)
    fuzzy_title_threshold: int = Field(default=86, ge=0, le=100)
    ats_companies: AtsCompanies = Field(default_factory=AtsCompanies)
    sources: SourceSettings = Field(default_factory=SourceSettings)
    email: EmailSettings
    resume: ResumeSettings = Field(default_factory=ResumeSettings)

    @field_validator("target_roles", "include_keywords", "exclude_keywords")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        terms = [value.strip() for value in values]
        if any(not value for value in terms):
            raise ValueError("terms cannot be blank")
        return terms


def load_config(path: Path) -> AppConfig:
    """Read YAML and reject missing, malformed, or unknown settings."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a YAML mapping")
    return AppConfig.model_validate(raw)
