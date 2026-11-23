"""Public job source adapters."""

from internship_bot.sources.base import Source, SourceResult
from internship_bot.sources.registry import build_sources
from internship_bot.sources.runner import fetch_all

__all__ = ["Source", "SourceResult", "build_sources", "fetch_all"]
