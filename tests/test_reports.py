"""Tests for reports + MCP server tool behavior."""
import tempfile
from pathlib import Path

from apply_jobs_mcp.config import Config
from apply_jobs_mcp.jobs import ingest_job
from apply_jobs_mcp.reports import build_report, build_status, export_report
from apply_jobs_mcp.storage import Store

ROOT = Path(__file__).resolve().parent.parent
CFG = Config.load(ROOT / "config.example.toml")


def _seed(store: Store):
    ingest_job(CFG, store, {
        "url": "https://internshala.com/internships/detail/201/",
        "title": "Software Engineer Intern",
        "employer": "Acme",
        "location": "Bangalore",
        "description": "Rust backend intern, REST APIs, Python.",
        "compensation_raw": "Rs 35000/month",
    })
    ingest_job(CFG, store, {
        "url": "https://internshala.com/internships/detail/202/",
        "title": "SWE Intern",
        "employer": "Beta",
        "description": "C++ intern, systems programming.",
        "compensation_raw": "Rs 15000/month",
    })


def test_build_report_summary():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "dbs.sqlite3")
        _seed(s)
        rep = build_report(s)
        assert rep["summary"].get("eligible") == 1
        assert rep["summary"].get("low_compensation") == 1
        assert len(rep["jobs"]) == 2
        s.close()


def test_export_report():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "dbs.sqlite3")
        _seed(s)
        paths = export_report(s, Path(tmp) / "reports")
        md = paths["markdown"].read_text(encoding="utf-8")
        js = paths["json"].read_text(encoding="utf-8")
        assert "Acme" in md
        assert "## Applications" in md
        assert "No applications have been prepared or submitted." in md
        assert "eligible" in md
        assert '"eligible"' in js
        s.close()


def test_status_includes_application_history():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "db.sqlite3")
        _seed(s)
        job = s.get_job(1)
        app_id = s.add_application({"job_id": job["id"], "job_snapshot": job})
        s.add_event("prepare", f"app {app_id}: {job['title']}")
        status = build_status(s)
        assert status["jobs"]["total"] == 2
        assert status["applications"]["total"] == 1
        assert status["applications"]["by_status"] == {"prepared": 1}
        assert status["applications"]["history"][0]["employer"] == "Acme"
        assert status["applications"]["recent_events"][0]["kind"] == "prepare"
        s.close()
