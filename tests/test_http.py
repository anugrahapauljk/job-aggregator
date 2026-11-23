"""Retry and cache behavior for public JSON requests."""

from pathlib import Path

import httpx
import pytest
import respx

from internship_bot.sources.http import get_json


@respx.mock
def test_retry_after_and_cache(tmp_path: Path) -> None:
    route = respx.get("https://example.com/api").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"data": [1]}),
        ]
    )
    with httpx.Client() as client:
        first = get_json(
            client, "https://example.com/api", {"page": 1}, cache_dir=tmp_path, cache_ttl_minutes=60
        )
        second = get_json(
            client, "https://example.com/api", {"page": 1}, cache_dir=tmp_path, cache_ttl_minutes=60
        )
    assert first == second == {"data": [1]}
    assert route.call_count == 2


@respx.mock
def test_long_retry_after_does_not_retry_early(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("internship_bot.sources.http.time.sleep", sleeps.append)
    route = respx.get("https://example.com/api").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"})
    )
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        get_json(client, "https://example.com/api", {})
    assert route.call_count == 1 and sleeps == []
