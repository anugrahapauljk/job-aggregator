"""Common contract for source adapters and their outcomes."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from internship_bot.models import Job


class Source(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def complete_inventory(self) -> bool: ...

    def fetch(self, client: httpx.Client) -> list[Job]: ...


@dataclass(frozen=True, slots=True)
class SourceResult:
    name: str
    status: str
    jobs: list[Job]
    raw_count: int | None = None
    warning: str | None = None
    complete_inventory: bool = False


class SourceSkipped(Exception):
    """The source is intentionally unavailable this run."""


@dataclass(frozen=True, slots=True)
class DisabledSource:
    name: str
    reason: str
    complete_inventory: bool = False

    def fetch(self, client: httpx.Client) -> list[Job]:
        raise SourceSkipped(self.reason)
