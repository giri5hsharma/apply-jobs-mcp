"""MCP server over stdio (official mcp SDK 2.x) exposing the job pipeline.

Learning notes:
- Tools are thin wrappers over small pure-ish modules (profile, jobs, policy,
  reports). The MCP layer only translates a request into a handler call.
- Tool signatures (types + docstrings) become the schema clients see, so
  keep them descriptive.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from . import __version__
from .browser import BrowserSession
from .config import Config
from .documents import make_application_package
from .jobs import ingest_job, public_scan
from .profile import load_profile
from .reports import build_status, export_report as write_report
from .runner import apply_batch as prepare_batch
from .sources import SOURCES
from .storage import Store

_SESSIONS: dict[int, BrowserSession] = {}


def verify_token(app_id: int, token: str) -> str | None:
    """Confirmation token must be tied to exactly this application."""
    expected = f"CONFIRM-{app_id}"
    if token != expected:
        return f"token mismatch (expected {expected})"
    return None


def _path(name: str) -> Path:
    env = os.environ.get(name)
    return Path(env) if env else Path.cwd() / name


def _config() -> Config:
    return Config.load(_path("AJM_CONFIG"))


def _store(cfg: Config) -> Store:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return Store(cfg.data_dir / "applications.sqlite3")


def create_server() -> MCPServer:
    mcp = MCPServer("apply-jobs-mcp")

    @mcp.tool()
    def ping() -> str:
        """Health check. Returns server name and version."""
        return f"apply-jobs-mcp {__version__}"

    @mcp.tool()
    def get_profile() -> dict[str, Any]:
        """Structured resume data parsed from the canonical cv.tex."""
        return load_profile(_config().resume_tex).to_dict()

    @mcp.tool()
    def get_campaign() -> dict[str, Any]:
        """Current campaign policy (thresholds, dates, roles, limits)."""
        c = _config().campaign
        import dataclasses

        return dataclasses.asdict(c)

    @mcp.tool()
    def list_sources() -> dict[str, Any]:
        """Approved job sources and their modes (public = no login)."""
        return {sid: {"label": m["label"], "mode": m["mode"],
                      "domains": m["domains"]} for sid, m in SOURCES.items()}

    @mcp.tool()
    def add_job_url(
        url: str,
        title: str = "",
        employer: str = "",
        location: str = "",
        description: str = "",
        compensation_raw: str = "",
    ) -> dict[str, Any]:
        """Ingest one job from an approved source URL: grade + store it.

        Returns the verdict (status/score/reasons) - never auto-applies.
        """
        cfg = _config()
        store = _store(cfg)
        try:
            return ingest_job(cfg, store, {
                "url": url,
                "title": title,
                "employer": employer,
                "location": location,
                "description": description,
                "compensation_raw": compensation_raw,
            })
        finally:
            store.close()

    @mcp.tool()
    def scan_source(source_id: str, keywords: str = "intern") -> list[dict[str, Any]]:
        """Public scan of one approved source (no login). Grades + stores."""
        cfg = _config()
        store = _store(cfg)
        try:
            return public_scan(cfg, store, source_id, keywords)
        finally:
            store.close()

    @mcp.tool()
    def list_jobs(status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """List stored jobs, optionally filtered by status. Top-scored first."""
        cfg = _config()
        store = _store(cfg)
        try:
            rows = store.list_jobs(status or None, limit)
        finally:
            store.close()
        for r in rows:
            r["description"] = r["description"][:400]
        return rows

    @mcp.tool()
    def get_status() -> dict[str, Any]:
        """Current job counts, all application states, and recent application history."""
        store = _store(_config())
        try:
            return build_status(store)
        finally:
            store.close()

    @mcp.tool()
    def inspect_job(job_id: int) -> dict[str, Any]:
        """Full details + policy verdict for one job id."""
        store = _store(_config())
        try:
            row = store.get_job(job_id)
            return row or {"error": f"no job {job_id}"}
        finally:
            store.close()

    @mcp.tool()
    def export_report() -> dict[str, str]:
        """Write applications.json + applications.md into output/reports."""
        cfg = _config()
        store = _store(cfg)
        try:
            paths = write_report(store, cfg.output_dir / "reports")
        finally:
            store.close()
        return {k: str(v) for k, v in paths.items()}

    @mcp.tool()
    def prepare_application(job_id: int, allow_review: bool = False) -> dict[str, Any]:
        """Create one application package: tailored resume.tex + PDF + cover letter.

        Only eligible jobs can be prepared. Set allow_review=true for a
        needs_review job (comp/visa uncertainty) AFTER you inspect it -
        the package is still never submitted automatically.
        """
        cfg = _config()
        store = _store(cfg)
        try:
            return make_application_package(cfg, store, job_id, allow_review=allow_review)
        finally:
            store.close()

    @mcp.tool()
    def apply_batch(score_min: float = 25.0) -> dict[str, Any]:
        """Prepare application packages for ALL eligible jobs with score > score_min.

        This is the batch "apply" step: packages get built (tailored resume
        PDF + cover letter + docs). Nothing is submitted - each application
        still needs review + a CONFIRM-<id> token via confirm_submission.
        """
        cfg = _config()
        store = _store(cfg)
        try:
            return prepare_batch(cfg, store, score_min=score_min)
        finally:
            store.close()

    @mcp.tool()
    def review_application(app_id: int) -> dict[str, Any]:
        """Show a prepared application: job, docs, answers, policy snapshot."""
        store = _store(_config())
        try:
            app = store.get_application(app_id)
        finally:
            store.close()
        if not app:
            return {"error": f"no application {app_id}"}
        return {
            "application_id": app["id"],
            "status": app["status"],
            "job": {k: app["job_snapshot"].get(k, "") for k in
                    ("title", "employer", "url", "location", "status", "compensation_raw")},
            "policy_snapshot": app["policy_snapshot"],
            "files": {
                "resume_tex": app["resume_tex"],
                "cover_letter": app["cover_letter"],
            },
            "form_answers": app["form_answers"],
            "hint": "call open_application, then fill_application, then "
                    "confirm_submission with token CONFIRM-<id>",
        }

    @mcp.tool()
    def pending_applications() -> list[dict[str, Any]]:
        """Applications waiting for review: prepared or filled-but-not-submitted."""
        store = _store(_config())
        try:
            rows = store.list_applications()
        finally:
            store.close()
        return [
            {"id": a["id"], "status": a["status"],
             "job": a["job_snapshot"].get("title", ""),
             "employer": a["job_snapshot"].get("employer", "")}
            for a in rows if a["status"] in ("prepared", "filled_waiting_for_submit")
        ]

    @mcp.tool()
    def open_application(app_id: int) -> dict[str, Any]:
        """Open the job in a visible, isolated browser (manual login OK).

        Browsing is explicit: this tool is never invoked on its own.
        """
        cfg = _config()
        store = _store(cfg)
        try:
            app = store.get_application(app_id)
            if not app:
                return {"error": f"no application {app_id}"}
            url = app["job_snapshot"].get("url", "")
            if not url:
                return {"error": "application has no job URL"}
            if app_id in _SESSIONS:
                try:
                    _SESSIONS[app_id].__exit__()
                finally:
                    del _SESSIONS[app_id]
            session = BrowserSession(cfg)
            session.__enter__()
            _SESSIONS[app_id] = session
            return {"opened": True, "url": url, **session.open_job(url)}
        except Exception as e:
            return {"error": str(e)}
        finally:
            store.close()

    @mcp.tool()
    def fill_application(app_id: int) -> dict[str, Any]:
        """Type profile answers into recognised form fields; NEVER guesses.

        Unknown/unrecognised fields are reported - answer those manually in
        the visible browser. Pauses: nothing is submitted here.
        """
        cfg = _config()
        store = _store(cfg)
        try:
            app = store.get_application(app_id)
            if not app:
                return {"error": f"no application {app_id}"}
            session = _SESSIONS.get(app_id)
            if session is None:
                return {"error": "no browser session; call open_application first"}
            cover_text = ""
            cover_path = app.get("cover_letter", "")
            if cover_path and Path(cover_path).exists():
                cover_text = Path(cover_path).read_text(encoding="utf-8")
            result = session.fill_known_fields(
                app["form_answers"], app.get("resume_pdf") or "", cover_letter_text=cover_text
            )
            if not result["resume_attached"]:
                result["error"] = "no resume PDF attached; check the application package and try again"
                return result
            store.update_application(app_id, status="filled_waiting_for_submit")
            store.add_event("filled", f"app {app_id}")
            return result
        finally:
            store.close()

    @mcp.tool()
    def confirm_submission(app_id: int, token: str) -> dict[str, Any]:
        """SUBMIT one application - only with the exact CONFIRM-<id> token.

        The token is deliberately required so an agent can never submit
        without the user deciding and spelling it out.
        """
        err = verify_token(app_id, token)
        if err:
            return {"error": err, "hint": f"expected token: CONFIRM-{app_id}"}
        cfg = _config()
        store = _store(cfg)
        try:
            app = store.get_application(app_id)
            if not app:
                return {"error": f"no application {app_id}"}
            if app["status"] != "filled_waiting_for_submit":
                return {"error": "application must be filled and reviewed before submission"}
            from datetime import datetime
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(cfg.schedule.get("timezone", "Asia/Kolkata"))
            today = datetime.now(zone).date()
            attempts = sum(
                datetime.fromisoformat(event["at"]).astimezone(zone).date() == today
                for event in store.events("submit_attempt", limit=10000)
            )
            if attempts >= cfg.campaign.max_submissions_per_day:
                return {"error": "daily submission limit reached"}
            session = _SESSIONS.get(app_id)
            if session is None:
                return {"error": "browser session missing; call open_application first"}
            store.add_event("submit_attempt", f"app {app_id}")
            outcome = session.submit()
            if not outcome["clicked"]:
                return {"error": outcome["page_text"]}
            confirmed = outcome["confirmed"]
            store.update_application(
                app_id,
                status="submitted" if confirmed else "submission_unverified",
                submitted_at=(__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                              if confirmed else ""),
                confirmation=outcome["page_text"][:400],
            )
            store.add_event("submit", f"app {app_id} confirmed={confirmed}")
            return {
                "application_id": app_id,
                "submitted": confirmed,
                "url": outcome["url"],
                "confirmation": outcome["page_text"][:400],
            }
        finally:
            store.close()

    return mcp


mcp = create_server()

if __name__ == "__main__":
    mcp.run()
