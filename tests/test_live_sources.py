"""Explicitly opt-in checks against every configured real source."""

from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

from internship_bot.config import load_config
from internship_bot.sources.base import DisabledSource
from internship_bot.sources.registry import build_sources

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
CONFIG = load_config(ROOT / "config.yaml")
SOURCES = build_sources(CONFIG)


@pytest.mark.live
@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.name)
def test_configured_live_source_returns_listings(source: object) -> None:
    if isinstance(source, DisabledSource):
        pytest.skip(source.reason)
    assert hasattr(source, "fetch")
    with httpx.Client(timeout=30) as client:
        assert source.fetch(client)  # type: ignore[attr-defined]
