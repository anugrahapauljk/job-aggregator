"""Construct configured public sources, isolating each ATS company board."""

import os
from pathlib import Path

from internship_bot.config import AppConfig
from internship_bot.sources.adzuna import AdzunaSource
from internship_bot.sources.ats import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    SmartRecruitersSource,
)
from internship_bot.sources.base import DisabledSource, Source
from internship_bot.sources.himalayas import HimalayasSource
from internship_bot.sources.internshala import InternshalaSource
from internship_bot.sources.linkedin import LinkedInSource
from internship_bot.sources.remoteok import RemoteOkSource
from internship_bot.sources.unstop import UnstopSource


def build_sources(config: AppConfig, cache_dir: Path | None = None) -> list[Source]:
    limit = config.sources.max_results_per_source
    sources: list[Source] = [
        RemoteOkSource(),
        HimalayasSource(max_results=limit),
        UnstopSource(
            max_results=limit,
            search_terms=tuple(config.sources.unstop_search_terms),
            max_pages=config.sources.unstop_max_pages,
            max_age_days=config.sources.max_posting_age_days,
            request_delay_seconds=config.sources.request_delay_seconds,
            cache_ttl_minutes=config.sources.cache_ttl_minutes,
            cache_dir=cache_dir,
        ),
    ]
    if config.sources.linkedin_enabled and config.sources.linkedin_search_terms:
        sources.append(
            LinkedInSource(
                search_terms=tuple(config.sources.linkedin_search_terms),
                results_per_query=config.sources.linkedin_results_per_query,
                hours_old=config.sources.linkedin_hours_old,
                request_delay_seconds=config.sources.request_delay_seconds,
                cache_ttl_minutes=config.sources.cache_ttl_minutes,
                cache_dir=cache_dir,
            )
        )
    else:
        sources.append(DisabledSource("linkedin", "disabled or no search terms configured"))
    if config.sources.internshala_enabled and config.sources.internshala_slugs:
        sources.append(
            InternshalaSource(
                slugs=tuple(config.sources.internshala_slugs),
                max_pages=config.sources.internshala_max_pages,
                max_results=limit,
                request_delay_seconds=config.sources.request_delay_seconds,
                cache_ttl_minutes=config.sources.cache_ttl_minutes,
                cache_dir=cache_dir,
            )
        )
    else:
        sources.append(DisabledSource("internshala", "disabled or no slugs configured"))
    boards = (
        ("greenhouse", config.ats_companies.greenhouse, GreenhouseSource),
        ("lever", config.ats_companies.lever, LeverSource),
        ("ashby", config.ats_companies.ashby, AshbySource),
        ("smartrecruiters", config.ats_companies.smartrecruiters, SmartRecruitersSource),
    )
    for family, slugs, adapter in boards:
        if slugs:
            sources.extend(adapter(slug) for slug in slugs)
        else:
            sources.append(DisabledSource(family, "no company slugs configured"))

    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if app_id and app_key:
        sources.append(AdzunaSource(app_id, app_key, max_results=limit))
    else:
        sources.append(DisabledSource("adzuna", "ADZUNA_APP_ID/ADZUNA_APP_KEY not set"))

    sources.extend(
        [
            DisabledSource("indeed", "automated extraction requires written permission"),
            DisabledSource("google_jobs", "Google search path is disallowed by robots.txt"),
            DisabledSource("naukri", "access policy could not be verified"),
        ]
    )
    return sources
