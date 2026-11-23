"""Digest selection, rendering, and send safety."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from internship_bot.digest import (
    DigestJob,
    mark_sent,
    render_digest,
    select_unsent,
    send_digest,
    sources_needing_attention,
)
from internship_bot.storage import database, initialize_database


def test_render_escapes_html_and_includes_both_sections() -> None:
    jobs = [
        DigestJob(
            i, f"Intern <{i}>", "A & B", "board", None, None, "https://example.com/?a=1&b=2", 5
        )
        for i in range(4)
    ]
    digest = render_digest(jobs, ["board"], datetime(2026, 11, 23, tzinfo=UTC))
    assert digest.subject == "4 new remote internships - 2026-11-23"
    assert "Top matches" in digest.html and "Other new listings" in digest.html
    assert "Sources needing attention" in digest.text
    assert "Intern &lt;0&gt;" in digest.html and "A &amp; B" in digest.html
    assert "?a=1&amp;b=2" in digest.html
    assert "not stated" in digest.text


def test_select_unsent_and_mark_only_selected(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        for number in range(3):
            connection.execute(
                """INSERT INTO jobs (canonical_key, title, company, location, apply_url,
                remote, internship, score, first_seen, last_seen)
                VALUES (?, ?, 'Example', 'Remote India', 'https://example.com',
                1, 1, ?, '2026-11-23', '2026-11-23')""",
                (str(number), f"Intern {number}", number),
            )
        selected = select_unsent(connection, 2)
        assert [job.title for job in selected] == ["Intern 2", "Intern 1"]
        mark_sent(connection, tuple(job.id for job in selected))
        assert [job.title for job in select_unsent(connection, 10)] == ["Intern 0"]


def test_source_health_requires_three_consecutive_successful_zero_runs(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    initialize_database(path)
    with database(path) as connection:
        for status, count in [("success", 0), ("success", 0), ("success", 0)]:
            connection.execute(
                "INSERT INTO source_runs (source, started_at, status, raw_count) "
                "VALUES ('board', 'now', ?, ?)",
                (status, count),
            )
        assert sources_needing_attention(connection) == ["board"]
        connection.execute(
            "INSERT INTO source_runs (source, started_at, status, raw_count) "
            "VALUES ('board', 'now', 'failed', 0)"
        )
        assert sources_needing_attention(connection) == []


def test_send_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_APP_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="SMTP_USERNAME"):
        send_digest(render_digest([], []), "user@example.com")


def test_smtp_uses_starttls_and_multipart_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert (host, port, timeout) == ("smtp.gmail.com", 587, 30)
            self.started_tls = False

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def ehlo(self) -> None:
            pass

        def starttls(self) -> None:
            self.started_tls = True

        def login(self, username: str, password: str) -> None:
            assert self.started_tls
            assert (username, password) == ("sender@gmail.com", "secret")

        def send_message(self, message: object) -> None:
            from email.message import EmailMessage

            assert isinstance(message, EmailMessage)
            assert message["To"] == "recipient@example.com"
            assert message.get_body(preferencelist=("plain",)) is not None
            assert message.get_body(preferencelist=("html",)) is not None

    monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "secret")
    monkeypatch.setattr("internship_bot.digest.smtplib.SMTP", FakeSMTP)
    send_digest(render_digest([], []), "recipient@example.com")
