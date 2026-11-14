"""Aggregate reports: applications.json + applications.md from the Store.

Learning notes:
- Reports are a pure projection of SQLite: any step of the pipeline can be
  verified by reading the report, and no report is ever "hand edited".
  Markdown is for humans, JSON is for machines, SQLite is the source.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import Store


def build_report(store: Store) -> dict[str, Any]:
    jobs = store.list_jobs(limit=500)
    apps = store.list_applications()
    summary: dict[str, int] = {}
    for j in jobs:
        summary[j["status"]] = summary.get(j["status"], 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "jobs": [
            {
                "id": j["id"],
                "url": j["url"],
                "source": j["source_id"],
                "title": j["title"],
                "employer": j["employer"],
                "location": j["location"],
                "remote": j["remote"],
                "compensation_raw": j["compensation_raw"],
                "compensation_inr_monthly": j["compensation_inr_monthly"],
                "currency": j["currency"],
                "status": j["status"],
                "score": j["role_match_score"],
                "reasons": j["reasons"],
                "visa_support": j["visa_support"],
                "discovered_at": j["discovered_at"],
            }
            for j in jobs
        ],
        "applications": [
            {
                "id": a["id"],
                "job_id": a["job_id"],
                "title": a["job_snapshot"].get("title", ""),
                "employer": a["job_snapshot"].get("employer", ""),
                "url": a["job_snapshot"].get("url", ""),
                "campaign_id": a["campaign_id"],
                "status": a["status"],
                "created_at": a["created_at"],
                "submitted_at": a["submitted_at"],
                "confirmation": a["confirmation"],
                "error": a["error"],
            }
            for a in apps
        ],
        "application_events": [event for event in store.events(limit=1000)
                               if event["kind"] in {"prepare", "filled", "submit_attempt", "submit"}],
    }


def build_status(store: Store, application_limit: int = 20) -> dict[str, Any]:
    """Current job counts plus every application state and recent action history."""
    jobs_by_status = {row["status"]: row["count"] for row in store.conn.execute(
        "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status")}
    apps = store.list_applications()
    apps_by_status: dict[str, int] = {}
    for app in apps:
        apps_by_status[app["status"]] = apps_by_status.get(app["status"], 0) + 1
    history = [{
        "id": app["id"],
        "job_id": app["job_id"],
        "title": app["job_snapshot"].get("title", ""),
        "employer": app["job_snapshot"].get("employer", ""),
        "url": app["job_snapshot"].get("url", ""),
        "status": app["status"],
        "created_at": app["created_at"],
        "submitted_at": app["submitted_at"],
        "confirmation": app["confirmation"],
        "error": app["error"],
    } for app in reversed(apps[-max(1, min(application_limit, 100)):])]
    application_events = [event for event in store.events(limit=1000)
                          if event["kind"] in {"prepare", "filled", "submit_attempt", "submit"}][:50]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": {"total": sum(jobs_by_status.values()), "by_status": jobs_by_status},
        "applications": {"total": len(apps), "by_status": apps_by_status,
                         "history": history, "recent_events": application_events},
        "recent_scans": store.events("scan", limit=10),
    }


def export_report(store: Store, report_dir: str | Path) -> dict[str, Path]:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = build_report(store)

    json_path = report_dir / "applications.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"# Job applications report ({payload['generated_at']})", ""]
    if payload["summary"]:
        lines.append("## Summary")
        for status in sorted(payload["summary"]):
            lines.append(f"- {status}: {payload['summary'][status]}")
        lines.append("")
    lines.append("## Applications")
    if not payload["applications"]:
        lines.extend(["No applications have been prepared or submitted.", ""])
    else:
        for app in reversed(payload["applications"]):
            lines.append(f"### #{app['id']} {app['title']} - {app['employer']}")
            lines.append(f"- Status: {app['status']} | Created: {app['created_at']}")
            if app["submitted_at"]:
                lines.append(f"- Submitted: {app['submitted_at']}")
            if app["confirmation"]:
                lines.append(f"- Confirmation: {app['confirmation']}")
            if app["error"]:
                lines.append(f"- Error: {app['error']}")
            lines.extend([f"- Link: {app['url']}", ""])
    if payload["application_events"]:
        lines.append("### Application activity")
        for event in payload["application_events"]:
            lines.append(f"- {event['at']}: {event['kind']} - {event['detail']}")
        lines.append("")
    lines.append("## Jobs")
    for j in sorted(payload["jobs"], key=lambda x: -x["score"]):
        comp = j["compensation_inr_monthly"]
        comp_s = f"₹{comp:,.0f}/mo" if comp is not None else j["compensation_raw"] or "n/a"
        loc = j["location"] or "n/a"
        lines.append(
            f"### {j['title']} - {j['employer'] or 'n/a'} "
            f"({j['status']}, score {j['score']:.0f})"
        )
        lines.append(f"- Source: {j['source']} | Location: {loc} | Comp: {comp_s}")
        lines.append(f"- Link: {j['url']}")
        if j["reasons"]:
            lines.append(f"- Why: {', '.join(j['reasons'])}")
        lines.append("")
    md_path = report_dir / "applications.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
