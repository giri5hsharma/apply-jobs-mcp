"""Tests for Greenhouse/Ashby public ATS adapters (fixture-based, offline)."""
import json

from apply_jobs_mcp.adapters import ASHBY_BOARDS, scan_ashby, scan_greenhouse, scan_greenhouse_board
from apply_jobs_mcp.sources import find_source

GH = json.dumps({
    "jobs": [
        {
            "id": 6136160004,
            "title": "Software Engineer Intern (2027)",
            "absolute_url": "https://job-boards.greenhouse.io/vercel/jobs/6136160004",
            "location": {"name": "Remote"},
            "content": "<p><strong>Compensation:</strong> $60/hr</p><ul><li>Rust backend</li></ul>",
        },
        {
            "id": 42,
            "title": "Data Platform Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/vercel/jobs/42",
            "location": {"name": "San Francisco"},
            "content": "<p>Kafka internals.</p>",
        },
    ]
})

ASHBY = json.dumps({
    "jobs": [
        {
            "id": "8fb1615c-34bf-47c4-affc-2b73df9e1e4a",
            "title": "Machine Learning Intern",
            "jobUrl": "https://jobs.ashbyhq.com/cursor/8fb1615c-34bf-47c4",
            "locationName": "Remote",
            "descriptionHtml": "<div>TS, distributed systems</div>",
            "compensation": {"summary": "$7,000/month"},
        }
    ]
})


def test_greenhouse_board(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.adapters.fetch_text", lambda *a, **k: GH)
    jobs = scan_greenhouse_board("vercel", "http://x")
    assert len(jobs) == 2
    first = jobs[0]
    assert first["title"] == "Software Engineer Intern (2027)"
    assert "$60/hr" in first["compensation_raw"]
    assert "Rust backend" in first["description"]
    assert find_source(first["url"]) == "greenhouse"


def test_ashby_board(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.adapters.fetch_text", lambda *a, **k: ASHBY)
    jobs = scan_ashby()
    assert len(jobs) == len(ASHBY_BOARDS)  # one fixture per live board token
    assert jobs[0]["title"] == "Machine Learning Intern"
    assert jobs[0]["compensation_raw"] == "$7,000/month"
    assert find_source(jobs[0]["url"]) == "ashby"


def test_board_urls_are_allowlisted():
    assert find_source("https://job-boards.greenhouse.io/vercel/jobs/1") == "greenhouse"
    assert find_source("https://jobs.ashbyhq.com/openai/posting-abc") == "ashby"


def test_greenhouse_keyword_filters_titles(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.adapters.GREENHOUSE_BOARDS", ["vercel"])
    monkeypatch.setattr("apply_jobs_mcp.adapters.fetch_text", lambda *a, **k: GH)
    jobs = scan_greenhouse("intern")
    assert [job["title"] for job in jobs] == ["Software Engineer Intern (2027)"]
