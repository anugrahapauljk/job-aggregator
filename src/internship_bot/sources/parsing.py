"""Small parsing helpers shared by API adapters."""

from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any


def string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("expected a list of jobs")
    return [item for item in value if isinstance(item, dict)]


def number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:  # ATS timestamps may be milliseconds.
            value /= 1000
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: Any) -> str:
    parser = _Text()
    parser.feed(string(value))
    return " ".join(unescape(" ".join(parser.parts)).split())


def required(value: Any, label: str) -> str:
    text = string(value)
    if not text:
        raise ValueError(f"source record has no {label}")
    return text
