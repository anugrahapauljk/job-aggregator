"""Select, render, and deliver the daily internship digest."""

import html
import os
import smtplib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class DigestJob:
    id: int
    title: str
    company: str
    source: str
    stipend_inr_per_month: float | None
    posted_at: str | None
    apply_url: str
    score: float


@dataclass(frozen=True, slots=True)
class Digest:
    subject: str
    text: str
    html: str
    job_ids: tuple[int, ...]


def select_unsent(connection: sqlite3.Connection, limit: int) -> list[DigestJob]:
    """Select the highest-ranked open jobs that have never been emailed."""
    rows = connection.execute(
        """SELECT j.id, j.title, j.company,
        COALESCE((SELECT group_concat(source, ', ') FROM
            (SELECT DISTINCT source FROM source_listings WHERE job_id = j.id ORDER BY source)),
            'unknown'),
        j.stipend_inr_per_month, j.posted_at, j.apply_url, j.score
        FROM jobs AS j WHERE j.status = 'open' AND j.sent_at IS NULL
        ORDER BY j.score DESC, j.first_seen DESC, j.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [DigestJob(*row) for row in rows]


def sources_needing_attention(connection: sqlite3.Connection) -> list[str]:
    """Alert when the latest three attempts for a source all succeeded with zero jobs."""
    sources = [row[0] for row in connection.execute("SELECT DISTINCT source FROM source_runs")]
    attention = []
    for source in sources:
        runs = connection.execute(
            "SELECT status, raw_count FROM source_runs WHERE source = ? ORDER BY id DESC LIMIT 3",
            (source,),
        ).fetchall()
        if len(runs) == 3 and all(status == "success" and count == 0 for status, count in runs):
            attention.append(source)
    return sorted(attention)


def _pay(job: DigestJob) -> str:
    if job.stipend_inr_per_month is None:
        return "not stated"
    return f"₹{job.stipend_inr_per_month:,.0f}/month"


def _posted(job: DigestJob) -> str:
    return job.posted_at[:10] if job.posted_at else "not stated"


def render_digest(
    jobs: list[DigestJob], attention: list[str], now: datetime | None = None
) -> Digest:
    """Render both mail alternatives from the same selected jobs."""
    date = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    subject = f"{len(jobs)} new remote internships - {date}"
    sections = [("Top matches", jobs[:3]), ("Other new listings", jobs[3:])]
    text_lines = [subject, ""]
    html_parts = [
        "<!doctype html><html><head><meta charset='utf-8'></head><body>",
        f"<h1>{html.escape(subject)}</h1>",
    ]
    for heading, entries in sections:
        if not entries:
            continue
        text_lines.extend([heading, ""])
        html_parts.append(f"<h2>{html.escape(heading)}</h2><ul>")
        for job in entries:
            text_lines.append(
                f"{job.title} — {job.company} | {job.source} | "
                f"Stipend: {_pay(job)} | Posted: {_posted(job)}\n{job.apply_url}\n"
            )
            html_parts.append(
                "<li><strong>"
                + html.escape(job.title)
                + "</strong> — "
                + html.escape(job.company)
                + "<br>Source: "
                + html.escape(job.source)
                + " | Stipend: "
                + html.escape(_pay(job))
                + " | Posted: "
                + html.escape(_posted(job))
                + '<br><a href="'
                + html.escape(job.apply_url, quote=True)
                + '">Apply</a></li>'
            )
        html_parts.append("</ul>")
    if attention:
        text_lines.extend(["Sources needing attention", *attention, ""])
        html_parts.append("<h2>Sources needing attention</h2><ul>")
        html_parts.extend(f"<li>{html.escape(source)}</li>" for source in attention)
        html_parts.append("</ul>")
    if not jobs:
        text_lines.append("No new remote internships today.")
        html_parts.append("<p>No new remote internships today.</p>")
    html_parts.append("</body></html>")
    return Digest(subject, "\n".join(text_lines), "".join(html_parts), tuple(j.id for j in jobs))


def preview_digest(digest: Digest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest.html, encoding="utf-8")


def send_digest(digest: Digest, recipient: str) -> None:
    """Send through Gmail SMTP with STARTTLS; credentials stay in the environment."""
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_APP_PASSWORD", "")
    if not username or not password:
        raise ValueError("SMTP_USERNAME and SMTP_APP_PASSWORD are required to send email")
    message = EmailMessage()
    message["From"] = username
    message["To"] = recipient
    message["Subject"] = digest.subject
    message.set_content(digest.text)
    message.add_alternative(digest.html, subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(message)


def mark_sent(connection: sqlite3.Connection, job_ids: tuple[int, ...]) -> None:
    """Record delivery only for the jobs included in the accepted message."""
    if job_ids:
        connection.executemany(
            "UPDATE jobs SET sent_at = ? WHERE id = ? AND sent_at IS NULL",
            [(datetime.now(UTC).isoformat(), job_id) for job_id in job_ids],
        )
