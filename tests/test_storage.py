import tempfile
from pathlib import Path

from apply_jobs_mcp.storage import Store


def test_job_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "x.sqlite3")
        jid = s.add_job({
            "url": "https://example.com/jobs/1",
            "source_id": "internshala",
            "employer": "Acme",
            "title": "Rust Intern",
            "description": "Work on backend services in Rust.",
            "compensation_raw": "Rs 30000/month",
            "status": "discovered",
        })
        row = s.get_job(jid)
        assert row["employer"] == "Acme"
        assert row["status"] == "discovered"
        s.close()


def test_same_url_updates_instead_of_dup():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "x.sqlite3")
        a = s.add_job({"url": "https://e.com/1", "title": "A", "employer": "X"})
        b = s.add_job({"url": "https://e.com/1", "title": "A2", "employer": "X"})
        assert a == b
        assert len(s.list_jobs()) == 1
        s.close()


def test_application_links_to_job():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "x.sqlite3")
        jid = s.add_job({"url": "https://e.com/2", "title": "T"})
        aid = s.add_application({
            "job_id": jid,
            "campaign_id": "summer-spring-2027",
            "policy_snapshot": {"min": 25000},
            "job_snapshot": {"title": "T"},
            "form_answers": {"q": "a"},
        })
        app = s.get_application(aid)
        assert app["job_id"] == jid
        assert app["policy_snapshot"] == {"min": 25000}
        assert app["form_answers"] == {"q": "a"}
        s.update_application(aid, status="submitted", submitted_at="2027-01-01T00:00:00")
        assert s.get_application(aid)["status"] == "submitted"
        s.close()


def test_events_logged():
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp) / "x.sqlite3")
        s.add_event("scan", "internshala done")
        s.add_event("submit", "app-1")
        kinds = [e["kind"] for e in s.events()]
        assert kinds == ["submit", "scan"]
        assert len(s.events(kind="scan")) == 1
        s.close()
