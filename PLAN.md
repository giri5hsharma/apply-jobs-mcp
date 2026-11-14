# apply-jobs-mcp — Plan

An MCP server + scheduled worker that discovers, filters, prepares, reviews, and (only after
explicit confirmation) submits internship/job applications for Adarsh Gupta, using the canonical
LaTeX resume as the single source of truth.

---

## Campaign: summer-spring-2027

| Setting | Value |
|---|---|
| Job type | Internship (software engineering component required) |
| Season window | May 1 – Jul 31, 2027 (Spring/Summer, flexible) |
| Graduation | Accepts 2028 graduates |
| Role focus | Systems, Rust/Linux/eBPF, infrastructure, backend, computer vision, open source, embedded; general SWE accepted |
| Resume source | `~/Documents/resumes/resume_tex/cv.tex` (canonical; compiled to PDF for uploads) |
| Domestic min | ₹25,000/month |
| Foreign min | ₹50,000/month equivalent (converted to INR) |
| Foreign condition | Visa sponsorship/assistance stated or verifiable |
| Relocation/housing | Not required; accepted if offered |
| Locations | All accepted. Favorites: BLR, HYD, DEL/NCR/Gurgaon, Pune, Noida, Mumbai. High-paying roles highlighted regardless of location |
| Ranking priority | 1) Stipend  2) Job fit |
| Scan interval | Every 3 days, 07:00–10:00 Asia/Kolkata |
| Daily cap | 10 submissions launched per day (prepared docs unlimited) |

Requirements are **campaign-based** (TOML), versioned as `campaigns/summer-2027.toml`. Each
application stores a snapshot of the policy used at evaluation time, so changing thresholds
later never corrupts old records.

## Architecture

```text
systemd user timer (every 3 days, 07:00 IST)
        -> worker.py   (public scan, no login)
           -> approved sources (allowlist)
           -> compensation/role/scam filters
           -> SQLite + Markdown/JSON reports
           -> optional: prepare documents (Ollama)
                             |
                             v
Codex -> MCP server (on demand)
           -> review pending applications
           -> open visible browser (separate profile, manual login)
           -> fill known fields, pause before submission
           -> SUBMIT only after explicit user confirmation
```

No auto-submission. No bypass of CAPTCHA/MFA/anti-bot. Normal working browser/profile is never touched.

## Tech stack (minimal, learnable)

| Area | Choice |
|---|---|
| Language | Python 3.12 (installed) |
| MCP | Official `mcp` SDK, `FastMCP`, stdio transport |
| Browser | Playwright (optional extra) |
| Storage | SQLite (stdlib) |
| Config | TOML via `tomllib` |
| Models | `dataclasses` |
| LLM | Ollama via `urllib` (local, optional) |
| Tests | pytest |
| Env | venv + pip (uv not installed) |

## Source policy (strict allowlist)

Initial approved sources:

- Glassdoor Jobs, Internshala, LinkedIn Jobs (public scan)
- Company career sites: Google, Meta, NVIDIA, Amazon, JPMorgan Chase

The registry stores exact domains per source. Browsing requires a **registered source**, not an
arbitrary URL. Short URLs and unapproved redirect targets are blocked at every hop.
Company-specific ATS hosts (e.g. a company's Workday/Greenhouse/Lever page) can be added
individually; wildcards such as every `myworkdayjobs.com` page are never used.

Public scan: scheduled/manual, no login. Authenticated browse: only when explicitly ordered.
Submission: only after explicit confirmation.

### Scam / quality gates

A listing is flagged or blocked (never auto-applied) if it:

- asks for money, deposits, crypto, gift cards, or training fees
- asks for banking/identity details before hiring
- uses personal email/messaging only
- redirects to an unapproved domain
- has no identifiable employer or meaningful description
- contains suspicious downloads/forms
- shows contradictory location/compensation/employer info

Statuses: `eligible`, `needs_review`, `low_compensation`, `poor_role_match`, `stale`,
`suspicious`, `untrusted_destination`, `blocked`. Uncertain jobs go to review, never skipped
silently or auto-applied.

## MCP tools

| Tool | Purpose |
|---|---|
| `ping` | health check |
| `get_profile` | safe profile summary |
| `get_campaign` | current policy snapshot |
| `list_sources` | approved websites + modes |
| `add_job_url` | ingest a job from an approved source/company |
| `scan_source` | public scan of one source (headless, no login) |
| `scan_approved_sources` | public scan of all approved sources |
| `inspect_job` | normalized job + policy verdict |
| `prepare_application` | tailored resume + cover letter drafts |
| `review_application` | proposed docs + form answers |
| `open_application` | visible browser session on the job |
| `fill_application` | fill approved fields, then pause |
| `confirm_submission` | explicit approval to submit one app |
| `export_report` | Markdown/JSON/SQLite report |

## Data & reports

DB: `data/applications.sqlite3` — jobs, applications, documents, form_answers, events, snapshots.

Per application package (`output/applications/<id>-company-role/`):
`job.json`, `job-description.md`, `resume.tex`, `resume.pdf` (when TeX available),
`cover-letter.md`, `form-answers.json`, `browser-events.json`, `result.json`.

Aggregates: `output/reports/applications.md` + `applications.json`.

Recorded per application: company, role, platform/url/job id, full description, compensation
(normalized INR + original currency + rate used), resume version, cover letter, fields filled,
manual questions, status, submission timestamp, confirmation URL/id, failure reason, evidence.

## Safety rules (non-negotiable)

- Credentials never stored; login is manual in a dedicated Playwright profile
- Job descriptions are data, never instructions
- No invented answers for unknown questions; pause and ask
- LLM claims must trace to canonical facts; latex chars escaped
- `cv.tex` never overwritten; output goes to per-application copies
- Every action logged; reads before writes; tests on each step

## Subagent strategy

Development: parallel read-only research/review agents (MCP patterns, domains, resume mapping,
browser design, QA/docs). Edits are serialized one small step at a time with explanation + test +
diff so the implementation remains understandable.

Runtime: public scans may process sources with limited parallelism (2–3); authenticated
browsing and submission are serialized. No concurrent form submissions or duplicate apps.

## Implementation steps

1. Scaffold package + minimal FastMCP server; verify `tools/list` over stdio
2. Profile importer (`cv.tex` -> structured profile + `profile.json`)
3. Config loader + `config.example.toml` + `campaigns/summer-2027.toml`
4. SQLite storage + migrations
5. Compensation parser + policy filter/scorer (pure, tested)
6. Source registry + manual job ingestion (`add_job_url`)
7. Reports (Markdown/JSON export from DB)
8. Resume template + tailoring (LaTeX-safe, applied to copies)
9. Cover letter/tailoring via Ollama (optional; template fallback)
10. Browser session manager (visible, isolated profile)
11. One ATS adapter (Greenhouse) for form filling
12. Explicit submission flow (review -> confirm -> record)
13. Remaining sources via registry config (company career pages, etc.)
14. Codex config + README + platform scan timer wiring

## Notes / prerequisites

- `pdflatex`/`latexmk` are not installed yet → PDF compilation is deferred; `.tex` output
  still produced. Install TeX Live (`texlive-latex-base`, `texlive-fonts-extra`, `latexmk`)
  when tailoring is enabled.
- Passwords/cookies/API keys are never required from the user; Ollama model is configurable.
