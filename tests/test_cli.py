"""CLI run and dry-run behavior."""

import smtplib
from pathlib import Path

import httpx
import pytest

from internship_bot.cli import main
from internship_bot.models import Job
from internship_bot.storage import database as open_database


def test_cli_initializes_database_and_writes_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("internship_bot.cli.build_sources", lambda config, cache_dir=None: [])
    config = Path(__file__).resolve().parents[1] / "config.yaml"
    database = tmp_path / "jobs.sqlite3"
    preview = tmp_path / "preview.html"
    assert (
        main(["dry-run", "--config", str(config), "--db", str(database), "--preview", str(preview)])
        == 0
    )
    assert database.exists()
    assert "No new remote internships today" in capsys.readouterr().out
    assert preview.exists()


def test_run_stores_jobs_but_dry_run_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExampleSource:
        name = "example"
        complete_inventory = False

        def fetch(self, client: httpx.Client) -> list[Job]:
            return [
                Job(
                    source=self.name,
                    source_id="one",
                    title="Backend Intern",
                    company="Example",
                    location="Remote India",
                    description="Build backend APIs",
                    apply_url="https://example.com/one",
                    remote=True,
                    india_eligible=True,
                )
            ]

    monkeypatch.setattr(
        "internship_bot.cli.build_sources", lambda config, cache_dir=None: [ExampleSource()]
    )
    config = Path(__file__).resolve().parents[1] / "config.yaml"
    path = tmp_path / "jobs.sqlite3"
    arguments = ["--config", str(config), "--db", str(path)]
    assert main(["dry-run", *arguments, "--preview", str(tmp_path / "preview.html")]) == 0
    with open_database(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone() == (0,)

    def fail_send(digest: object, recipient: str) -> None:
        raise smtplib.SMTPException("test failure")

    monkeypatch.setattr("internship_bot.cli.send_digest", fail_send)
    assert main(["run", *arguments]) == 1
    with open_database(path) as connection:
        assert connection.execute("SELECT COUNT(*), MAX(sent_at) FROM jobs").fetchone() == (1, None)
    monkeypatch.setattr("internship_bot.cli.send_digest", lambda digest, recipient: None)
    assert main(["run", *arguments]) == 0
    with open_database(path) as connection:
        count, sent_at = connection.execute("SELECT COUNT(*), MAX(sent_at) FROM jobs").fetchone()
        assert count == 1 and sent_at is not None
    assert main(["run", *arguments]) == 0
    with open_database(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs WHERE sent_at IS NULL").fetchone() == (
            0,
        )
