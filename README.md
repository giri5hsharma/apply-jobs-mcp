# apply-jobs-mcp

MCP server + scheduled worker that discovers, filters, and prepares internship
applications from an allowlisted set of sources, using the configured resume
as the source of truth for your profile. A PDF resume is copied into each
application package; a LaTeX resume can also be reordered and compiled. Nothing is submitted without an
explicit confirmation.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,browser]"     # browser extra is optional
.venv/bin/python -m pytest -q
```

The example configuration points to Girish Sharma's PDF resume in Downloads.
Edit `paths.resume_tex` in `config.toml` if the resume moves. This legacy
setting accepts either a `.pdf` or a `.tex` file. PDF text must be selectable
so the profile facts can be extracted. The generated application uses the
original PDF without rewriting it.

### Use the MCP server in Codex

```bash
codex mcp add apply-jobs-mcp -- /bin/bash "$PWD/deploy/run-codex-mcp.sh"
codex mcp list
```

Run the commands from this project directory. Restart Codex after adding the
server, then use `/mcp` in Codex to check that `apply-jobs-mcp` is connected.
The launcher uses this project's virtual environment and configuration.

### Scan for jobs (public, no login)

```bash
.venv/bin/python -m apply_jobs_mcp.worker --source amazon --keywords intern --print
.venv/bin/python -m apply_jobs_mcp.worker --source internshala --keywords software
```

Job data lands in `data/applications.sqlite3`; reports:

```bash
.venv/bin/python -c "from apply_jobs_mcp import reports; reports.export_report(reports.Store('data/applications.sqlite3'), 'output/reports')"
```

or via the MCP tool `export_report`.
In Codex, use `get_status` for job counts, prepared/submitted application counts,
recent application records, and the action history. The exported Markdown and
JSON reports also include application history.

## How it works

```text
public scan / add_job_url
      /  |  \
  sources.py (allowlist) -> policy.py (scam+comp+fit) -> storage.py
                                  |                            |
                            compensation.py              reports.py
```

- `sources.py` - only approved domains can ever be scanned or browsed.
- `policy.py` - eligibility, scam gates, stipend-first score.
- `compensation.py` - normalizes `Rs 25k/mo`, `3 LPA`, `$2,000/mo` -> INR/month.
- `profile.py` - parses the configured PDF or `cv.tex` into structured data; never writes the source.
- `storage.py` - SQLite (WAL). Jobs, applications, events.
- `reports.py` - Markdown + JSON exports.

## Campaign (changeable without code)

See `campaigns/summer-2027.toml` (stipend thresholds, visa rules, date window,
roles, daily cap, scan interval). Global settings: `config.example.toml`
(copy to `config.toml` to override).

## Safety model

- Submit flows require explicit confirmation and are not wired yet by design.
- Browsing outside approved domains / shorteners / unknown hosts is blocked.
- Credentials are never stored; logins are manual in a dedicated profile.
- Job descriptions are treated as data, never as instructions.

## Application lifecycle (MCP tools)

```text
scan_source / add_job_url      discover + grade (policy.py)
prepare_application(job_id)    package dir under output/applications/:
                                 resume.tex (tailored) + cover-letter.md
                                 + job.json + form-answers.json
review_application(app_id)     inspect package before touching a browser
open_application(app_id)       visible, isolated browser (manual login allowed)
fill_application(app_id)       fills only fields it recognises; reports the rest
confirm_submission(app_id,     submits ONLY with the exact token CONFIRM-<id>;
  token="CONFIRM-1")           records URL + confirmation, status 'submitted'
```

No step is automatic in series: review -> open -> fill -> confirm are four
separate decisions you approve in Codex.

## Scheduled scans (systemd user timer)

```bash
bash deploy/install.sh
# --> runs .venv/bin/python -m apply_jobs_mcp.worker --source all
#     every 3 days at 07:00 IST (day 1/4/7/... of each month)
```

Manual run anytime: `.venv/bin/python -m apply_jobs_mcp.worker --source internshala --keywords "software developer" --print`

On macOS, use `bash deploy/install-macos.sh` instead. It installs a LaunchAgent
that scans on days 1, 4, 7, and so on at 07:00 local time. Results stay in
`data/applications.sqlite3`; scan logs go to `data/scan.log` and `data/scan.err`.

## LLM (optional)

Set `llm.enabled = true` in `config.toml` to let Ollama
(`gemma4:31b-cloud`, local) write cover letters; the deterministic template
fallback is used otherwise. The model only sees the parsed profile + job text
and is instructed to never invent facts.

## Known notes

- PDF compilation needs TeX only when the source resume is `.tex`.
  With a PDF source, `prepare_application` copies it for attachment.
- Public scanners (no login): Internshala, Amazon, Greenhouse boards
  (9 live: stripe, vercel, reddit, cloudflare, mozilla, datadog, duolingo,
  discord, netlify), Ashby boards (openai, linear, cursor, perplexity, n8n).
- Browse-mode sources (login/JS, use `open_application`): LinkedIn, Glassdoor,
  Google/Meta/NVIDIA/JPMorgan careers, Naukri, Indeed, Wellfound.
- Policy is conservative: scam-adjacent wording must look like a payment
  demand on you, never a mention (Amazon payment-boilerplate safe); "intern"
  match is word-bounded so "internal tooling" doesn't sneak in.
- Workers default `--source all` = every source with a public scanner.

