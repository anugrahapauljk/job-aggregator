"""Bounded retries and short-lived cache for permitted public JSON endpoints."""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, str | int],
    *,
    cache_dir: Path | None = None,
    cache_ttl_minutes: int = 0,
) -> Any:
    key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    path = cache_dir / f"{key}.json" if cache_dir is not None else None
    if path is not None and cache_ttl_minutes:
        try:
            if time.time() - path.stat().st_mtime < cache_ttl_minutes * 60:
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                delay = _retry_after(response.headers.get("Retry-After"))
                if delay is not None and delay > 30:
                    response.raise_for_status()
                time.sleep(delay if delay is not None else 2.0**attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if path is not None and cache_ttl_minutes:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
                try:
                    temporary.write_text(json.dumps(payload), encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            return payload
        except (httpx.TransportError, httpx.DecodingError) as exc:
            if attempt == 2:
                raise exc
            time.sleep(2.0**attempt)
    raise RuntimeError("unreachable retry state")


def get_text(
    client: httpx.Client,
    url: str,
    *,
    cache_dir: Path | None = None,
    cache_ttl_minutes: int = 0,
    headers: dict[str, str] | None = None,
) -> str:
    """Fetch a public HTML listing page with the same bounded retry/cache policy."""
    key = hashlib.sha256(url.encode()).hexdigest()
    path = cache_dir / f"{key}.html" if cache_dir is not None else None
    if path is not None and cache_ttl_minutes:
        try:
            if time.time() - path.stat().st_mtime < cache_ttl_minutes * 60:
                return path.read_text(encoding="utf-8")
        except OSError:
            pass
    for attempt in range(3):
        try:
            response = client.get(url, headers=headers)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                delay = _retry_after(response.headers.get("Retry-After"))
                if delay is not None and delay > 30:
                    response.raise_for_status()
                time.sleep(delay if delay is not None else 2.0**attempt)
                continue
            response.raise_for_status()
            html = response.text
            if path is not None and cache_ttl_minutes:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
                try:
                    temporary.write_text(html, encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            return html
        except httpx.TransportError as exc:
            if attempt == 2:
                raise exc
            time.sleep(2.0**attempt)
    raise RuntimeError("unreachable retry state")
