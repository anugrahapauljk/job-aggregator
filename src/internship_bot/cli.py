"""One-shot command line entry point."""

import argparse
import os
import smtplib
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from internship_bot.config import load_config
from internship_bot.digest import (
    mark_sent,
    preview_digest,
    render_digest,
    select_unsent,
    send_digest,
    sources_needing_attention,
)
from internship_bot.fx import load_inr_rates
from internship_bot.pipeline import group_jobs
from internship_bot.sources import build_sources, fetch_all
from internship_bot.storage import database, initialize_database
from internship_bot.storage.jobs import StoreStats, upsert_jobs
from internship_bot.storage.stale import update_stale


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="internship-bot")
    parser.add_argument("command", choices=("run", "dry-run"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--db", type=Path, default=Path("data/jobs.sqlite3"))
    parser.add_argument("--preview", type=Path, default=Path("previews/digest.html"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stats: StoreStats | None = None
    try:
        load_dotenv(args.config.parent / ".env", override=False)
        config = load_config(args.config)
        recipient = os.environ.get("EMAIL_RECIPIENT", "").strip() or config.email.recipient
        if args.command == "run" and recipient is None:
            raise ValueError("EMAIL_RECIPIENT or email.recipient is required to send email")
        initialize_database(args.db)
        with httpx.Client(
            timeout=20,
            trust_env=True,
            headers={"User-Agent": "RemoteInternshipBot/0.1 (personal digest)"},
        ) as client:
            if args.command == "dry-run":
                with database(args.db) as original:
                    connection = sqlite3.connect(":memory:")
                    original.backup(connection)
                results = fetch_all(
                    build_sources(config, args.db.parent / "cache"), client, connection
                )
                raw_jobs = [job for result in results for job in result.jobs]
                rates = load_inr_rates(raw_jobs, client, connection)
                groups = group_jobs(raw_jobs, config, inr_rates=rates)
                upsert_jobs(connection, groups, config.fuzzy_title_threshold)
                update_stale(connection, results, config.sources.max_posting_age_days)
                jobs = select_unsent(connection, config.email.max_jobs_per_digest)
                attention = sources_needing_attention(connection)
                connection.close()
                digest = render_digest(jobs, attention)
                preview_digest(digest, args.preview)
                print(digest.text)
                print(f"HTML preview: {args.preview}")
            else:
                with database(args.db) as connection:
                    results = fetch_all(
                        build_sources(config, args.db.parent / "cache"), client, connection
                    )
                    raw_jobs = [job for result in results for job in result.jobs]
                    rates = load_inr_rates(raw_jobs, client, connection)
                    groups = group_jobs(raw_jobs, config, inr_rates=rates)
                    stats = upsert_jobs(connection, groups, config.fuzzy_title_threshold)
                    closed = update_stale(connection, results, config.sources.max_posting_age_days)
                    connection.commit()
                    jobs = select_unsent(connection, config.email.max_jobs_per_digest)
                    attention = sources_needing_attention(connection)
                    if jobs or config.email.send_no_new_jobs:
                        digest = render_digest(jobs, attention)
                        assert recipient is not None
                        send_digest(digest, recipient)
                        mark_sent(connection, digest.job_ids)
                        print(f"Sent digest with {len(jobs)} jobs.")
                    else:
                        print("No new jobs; no email sent.")
                    print(f"Closed {closed} stale jobs.")
    except (OSError, ValueError, ValidationError, sqlite3.Error, smtplib.SMTPException) as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1
    print(f"Loaded {len(config.target_roles)} target roles; database ready at {args.db}.")
    print(
        f"{args.command}: fetched {sum(len(result.jobs) for result in results)} raw jobs "
        f"from {sum(result.status == 'success' for result in results)} sources; "
        f"{sum(result.status == 'failed' for result in results)} failed, "
        f"{sum(result.status == 'skipped' for result in results)} skipped."
    )
    print(f"{len(groups)} listings match the configured filters after deduplication.")
    if stats is not None:
        print(
            f"Stored {stats.inserted} new jobs, refreshed {stats.updated}, "
            f"and linked {stats.source_listings} source listings."
        )
    for group in groups[:5]:
        job = group.primary
        print(f"- [{group.score:.1f}] {job.title} — {job.company} ({job.source}): {job.apply_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
