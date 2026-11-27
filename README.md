# Remote Internship Bot

A Python 3.11 program that sends a daily email digest of new remote internships open to applicants in India.

## Setup and run

```bash
cd remote-internship-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m internship_bot dry-run
python -m internship_bot run
pytest
ruff check .
ruff format --check .
mypy src
```

Both commands validate `config.yaml`, initialize `data/jobs.sqlite3`, fetch raw listings, and print the number of matching listings plus five ranked examples. `run` records source outcomes, stores matching jobs, and emails up to `email.max_jobs_per_digest` unsent jobs. It skips email when none are new unless `email.send_no_new_jobs` is true. `dry-run` works on an in-memory copy of the database, prints the digest, and writes `previews/digest.html` without sending or marking jobs sent. Use `--preview PATH` to change that location, and `--config PATH` and `--db PATH` to select other files. The database, cache, and previews are ignored by Git.

Inspect saved results with `sqlite3 data/jobs.sqlite3 'SELECT title, company, score, first_seen, last_seen, sent_at FROM jobs ORDER BY score DESC LIMIT 10;'`. Re-running `run` refreshes `last_seen` and retains `first_seen` and `sent_at`.

## Code layout

```text
src/internship_bot/
├── cli.py                # command line entry point
├── config.py             # validated YAML settings
├── models.py             # source-neutral job model
├── pipeline.py           # normalization, filters, ranking, exact and fuzzy deduplication
├── digest.py             # unsent selection, HTML/text rendering, SMTP, sent tracking
├── fx.py                 # daily FX lookup, cache, and outage fallback
├── sources/              # one adapter per public feed or ATS family
│   ├── base.py            # Source protocol and outcome
│   ├── registry.py        # configured source instances
│   ├── runner.py          # isolated fetch and source run log
│   └── ...                # RemoteOK, Himalayas, ATS, Unstop, LinkedIn, Internshala, Adzuna
└── storage/
    ├── database.py       # connection lifetime and initialization
    ├── jobs.py           # job/source upsert and delivery-history preservation
    ├── stale.py          # source-aware closure
    └── schema.sql        # SQLite tables and indexes
tests/                     # config, storage, CLI, and mocked source responses
```

The digest shows the top three ranked matches first, followed by other new listings. It includes each job's source, stipend or “not stated”, posted date, and apply link. If a source returned zero raw listings on each of its last three successful runs, the digest includes a “Sources needing attention” section. A failed or skipped run breaks that zero-result streak.

Edit `config.yaml` to change target roles, keyword lists, ATS company slugs, pay floor, and digest size. Set the recipient through `EMAIL_RECIPIENT`. `require_india_eligibility` keeps remote jobs only when an adapter establishes eligibility for applicants in India or applicants anywhere. An unclear eligibility claim is not treated as confirmed. Listings without stated pay remain eligible when a pay floor is set. Stated pay is converted to INR/month before the pay floor and ranking are applied. Hourly pay assumes 40 hours/week; daily pay assumes five days/week. Unsupported pay periods remain unstated.

Exact matches are grouped by normalized company, title, and location. A fuzzy title pass then groups near matches within the same company using `fuzzy_title_threshold`. Every source listing remains linked to the stored job. Ranking favors target-role phrases in titles, then descriptions, stated stipend, and recent posting dates. Missing posting dates remain eligible. When `max_experience_years` is above zero, the experience filter checks only explicitly labeled requirements or qualifications; a missing section is left unjudged.

## Secrets

Copy `.env.example` to `.env`. Set `SMTP_USERNAME` to your Gmail address, `SMTP_APP_PASSWORD` to a Gmail app password, and `EMAIL_RECIPIENT` to the digest destination before running `run` with new jobs. The bot uses `smtp.gmail.com:587` with STARTTLS. Keep addresses and passwords out of tracked files. `dry-run` needs no email credentials.

Set `HTTP_PROXY` or `HTTPS_PROXY` in `.env` if HTTP sources need a proxy; httpx reads these variables. `JOBSPY_PROXIES` is a separate comma-separated setting for LinkedIn. Each source is retried up to three times on transient network errors or HTTP 429/5xx, with exponential backoff and `Retry-After` where supplied. JobSpy queries have a configurable delay between search terms.

The bot requests [Frankfurter reference rates](https://frankfurter.dev/) for currencies actually present in fetched jobs, caches each INR rate in SQLite for one UTC day, and uses the last cached rate if the API fails. If no cached rate exists, a hand-written approximate fallback covers USD, EUR, GBP, CAD, AUD, SGD, and JPY; unsupported currencies keep pay unstated. Fallback amounts are estimates and should not be treated as current exchange quotes.

## Sources and access

Enabled without keys: RemoteOK, Himalayas, Unstop's `/api/public/` opportunity search, LinkedIn guest listings through `python-jobspy`, and Internshala public listing pages. Add company slugs to `config.yaml` to enable Greenhouse, Lever, Ashby, and SmartRecruiters. Each company board is isolated: failure on one board does not stop another. Adzuna is enabled only when `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are present in `.env` or the process environment. A source failure is logged and cannot close jobs.

The current fetch window for Himalayas, Unstop, and Adzuna is `sources.max_results_per_source`. Unstop searches the configured terms, walks up to `unstop_max_pages` per term, keeps open application windows, and uses `jobDetail.type` to identify work-from-home listings. Its requests are paced, retried on transient errors (including `Retry-After`), and cached for `cache_ttl_minutes`. `max_posting_age_days` filters old postings. RemoteOK returns its public feed. ATS boards return full inventories. For a successful full-inventory source, aliases absent from that source are deactivated. For a successful capped source, aliases expire only after the job's posting age exceeds `max_posting_age_days`. A job closes only when no active source alias remains. Failed or skipped sources cannot deactivate their listings.

## Daily deployment

The [daily workflow](.github/workflows/daily-digest.yml) is scheduled for 09:00 IST. It runs Ruff, mypy, and pytest before the bot. Set GitHub Actions secrets `SMTP_USERNAME`, `SMTP_PASSWORD` (the Gmail app password), and `BOT_STATE_KEY`. `EMAIL_RECIPIENT` is optional; the workflow uses `SMTP_USERNAME` as the destination when it is absent. Optionally set `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, and `JOBSPY_PROXIES`. Allow the workflow to write repository contents.

Generate `BOT_STATE_KEY` once with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` after installing dependencies. Save it as a GitHub Actions repository secret; keep a private backup because changing or losing it makes the saved history unreadable. The workflow restores `jobs.sqlite3.enc` from `bot-state`, decrypts it on the runner, and commits only ciphertext back to that branch. It saves the database even when the bot step fails, so fetched jobs remain unsent for a later retry. The first encrypted run can read the previous plaintext database and migrate it. **The older plaintext `bot-state` commits remain accessible in this public repository until their history is separately purged.** Do not add résumé data to this database. Use `workflow_dispatch` for a manual run after setting the secret. Scheduled GitHub workflows can start late.

Alternatively, run locally with a user systemd timer. Put these units under `~/.config/systemd/user/` (adjust the project path if needed):

```ini
# remote-internship-bot.service
[Unit]
Description=Remote internship digest
[Service]
Type=oneshot
WorkingDirectory=/path/to/remote-internship-bot
ExecStart=/path/to/remote-internship-bot/.venv/bin/python -m internship_bot run
```

```ini
# remote-internship-bot.timer
[Unit]
Description=Daily remote internship digest
[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

Replace `/path/to/remote-internship-bot` with the absolute path to your checkout. Run `systemctl --user daemon-reload` and `systemctl --user enable --now remote-internship-bot.timer`. The timer uses your local timezone. A cron alternative is `30 9 * * * cd /path/to/remote-internship-bot && .venv/bin/python -m internship_bot run`; cron also uses the machine's timezone. Keep the local SQLite file on persistent storage and avoid overlapping runs.

The optional live checks use `pytest -m live -q` and assert that each configured real source returns listings. They are skipped in normal CI because boards may block requests, return zero, or change without a code regression. Set ATS slugs and optional Adzuna keys to include those sources in a live check.

The LinkedIn and Internshala adapters follow the reference repository's public guest and listing-page approach. LinkedIn uses remote internship queries and requests descriptions; Internshala walks configured work-from-home filter slugs and parses HTML cards. Both are windowed sources and are never treated as full inventories. These routes may return zero or be rate limited. `JOBSPY_PROXIES` in `.env` accepts a comma-separated list if you have proxies available. **Access notice:** LinkedIn's [robots notice](https://www.linkedin.com/robots.txt) requires express permission for automated access, and Internshala's [terms](https://internshala.com/terms/) prohibit data extraction. Public access does not grant permission. Set `sources.linkedin_enabled` and `sources.internshala_enabled` to `false` to disable them. Indeed via jobspy ([terms](https://www.indeed.com/legal)) and Google Jobs via jobspy ([robots.txt](https://www.google.com/robots.txt)) remain skipped. Naukri via jobspy is skipped until its access policy can be verified.

The enabled endpoints are documented by [RemoteOK](https://remoteok.com/faq), [Himalayas](https://himalayas.app/docs/remote-jobs-api), [Greenhouse](https://docs.greenhouse.io/job-board.html), [Lever](https://github.com/lever/postings-api), [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api), [SmartRecruiters](https://developers.smartrecruiters.com/docs/endpoints), and [Adzuna](https://developer.adzuna.com/docs/search). [Unstop robots.txt](https://unstop.com/robots.txt) explicitly allows `/api/public/*`.

## Adding a source

Implement the `Source` protocol in `sources/base.py`, returning source-neutral `Job` records. Register the adapter in `sources/registry.py`. Mark `complete_inventory` true only if a successful fetch covers the whole board. Add a mocked HTTP response test for parsing and a failure case. The runner handles exceptions and logs each source independently.

## Known limitations

- An empty successful full-inventory ATS response is treated as a genuinely empty board and can close jobs from that board. Review source health alerts if a board changes its response format.
- SMTP delivery and the SQLite `sent_at` update cannot be atomic. A process crash after Gmail accepts the message but before the database commit can cause a repeat on the next run.
- The encrypted state branch can only preserve delivery history if its push succeeds. A push failure after email acceptance may cause a repeat on the next workflow run.
- LinkedIn and Internshala access is subject to their restrictions, and either adapter can stop working or return no jobs.
- Board access policies and response formats can change; live source checks remain necessary.
