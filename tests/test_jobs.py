"""Tests for the source registry, URL validation, and job ingestion."""
import tempfile
from pathlib import Path

import pytest

from apply_jobs_mcp.config import Config
from apply_jobs_mcp.jobs import ingest_job, scan_internshala, strip_tags
from apply_jobs_mcp.sources import BlockedURL, find_source, validate_url
from apply_jobs_mcp.storage import Store

ROOT = Path(__file__).resolve().parent.parent
CFG = Config.load(ROOT / "config.example.toml")


def _store():
    tmp = tempfile.TemporaryDirectory()
    s = Store(Path(tmp.name) / "x.sqlite3")
    return tmp, s


def test_allowlist_matches_known_sources():
    assert find_source("https://internshala.com/internships/detail/1234/") == "internshala"
    assert find_source("https://www.amazon.jobs/en/jobs/42") == "amazon"
    assert validate_url("https://careers.google.com/jobs/results?q=intern") == "google"


def test_shorteners_and_unknown_domains_blocked():
    with pytest.raises(BlockedURL):
        validate_url("https://bit.ly/x")
    with pytest.raises(BlockedURL):
        validate_url("https://evil-scam-jobs.com/intern")
    with pytest.raises(BlockedURL):
        validate_url("ftp://linkedin.com/x")


def test_ingest_eligible_and_flagged():
    tmp, s = _store()
    try:
        ok = ingest_job(CFG, s, {
            "url": "https://internshala.com/internships/detail/101/",
            "title": "Software Engineer Intern",
            "employer": "Acme",
            "location": "Bangalore",
            "description": "Rust backend intern with REST APIs in Python.",
            "compensation_raw": "Rs 30000/month",
        })
        assert ok["status"] == "eligible"
        assert ok["compensation_inr_monthly"] == 30000

        low = ingest_job(CFG, s, {
            "url": "https://internshala.com/internships/detail/102/",
            "title": "Software Engineer Intern",
            "employer": "Acme",
            "description": "Python backend intern focusing on REST APIs and database work.",
            "compensation_raw": "Rs 10000/month",
        })
        assert low["status"] == "low_compensation"

        bad = ingest_job(CFG, s, {
            "url": "https://internshala.com/internships/detail/103/",
            "title": "Software Engineer Intern",
            "employer": "Acme",
            "description": "Pay a registration fee of Rs 1000, email cv123@gmail.com.",
            "compensation_raw": "Rs 40000/month",
        })
        assert bad["status"] == "suspicious"
        assert any(e["kind"] == "ingest" for e in s.events())
    finally:
        s.close()
        tmp.cleanup()


def test_blocked_url_is_never_stored():
    tmp, s = _store()
    try:
        out = ingest_job(CFG, s, {"url": "https://bit.ly/x", "title": "X"})
        assert out["status"] == "blocked"
        # no 'ingest' event for a blocked URL, only a 'blocked' event
        assert not any(e["kind"] == "ingest" for e in s.events())
    finally:
        s.close()
        tmp.cleanup()


INTERNSHALA_FIXTURE = """
<div id='internship_list_container_1'>
<div class="container-fluid individual_internship logged_out_jd_summary  visibilityTrackerItem " id="individual_internship_3241046" internshipId="3241046" employment_type="internship" data-source_page=search_page data-href='/internship/detail/software-dev-intern-2027-at-acme-systems1786705262'>
  <div class="internship_meta duration_meta">
    <div class="internship-heading-container">
      <div class="company generic_company">
        <div class='generic_container'>
          <h2 class="job-internship-name">
            <a class="job-title-href" id="job_title" href="/internship/detail/software-dev-intern-2027-at-acme-systems1786705262" target="_blank">Software Development Intern (2027)</a>
          </h2>
        </div>
        <div class="heading_6 company_name">
          <div class="company_and_premium">
            <p class="company-name">Acme Systems Pvt Ltd</p>
          </div>
        </div>
      </div>
      <div class="internship_meta">
        <div class="row-1-item locations">
          <i class="ic-16-map-pin"></i>
          <span><a>Bengaluru</a> (On-site)</span>
        </div>
        <div class="row-1-item">
          <i class="ic-16-money"></i>
          <span class='stipend'>Rs 25,000/month</span>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="container-fluid individual_internship logged_out_jd_summary visibilityTrackerItem " id="individual_internship_3249999" internshipId="3249999" data-href='/internship/detail/rust-builder-intern-at-rustix1786723456'>
  <div class="company generic_company">
    <h2><a class="job-title-href" href="/internship/detail/rust-builder-intern-at-rustix1786723456">Rust Builds Intern</a></h2>
    <div class="heading_6 company_name"><p class="company-name">Rustix</p></div>
  </div>
  <div class="row-1-item locations"><span><a>Remote</a> (Remote)</span></div>
  <div class="row-1-item"><span class="stipend">Rs 50000 /month</span></div>
</div>
</div>
"""


def test_internshala_card_parser(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.jobs.fetch_text", lambda *a, **k: INTERNSHALA_FIXTURE)
    jobs = scan_internshala("software")
    assert len(jobs) == 2
    assert jobs[0]["title"] == "Software Development Intern (2027)"
    assert jobs[0]["job_id"] == "3241046"
    assert jobs[0]["employer"] == "Acme Systems Pvt Ltd"
    assert "25,000" in jobs[0]["compensation_raw"]
    assert jobs[0]["location"].startswith("Bengaluru")
    assert jobs[1]["title"] == "Rust Builds Intern"


def test_strip_tags():
    assert strip_tags("<b>Hi &amp; bye</b>") == "Hi & bye"


def test_software_scan_uses_category(monkeypatch):
    seen = []
    monkeypatch.setattr("apply_jobs_mcp.jobs.fetch_text", lambda url: seen.append(url) or INTERNSHALA_FIXTURE)
    scan_internshala("software")
    assert seen == ["https://internshala.com/internships/software-development-internship/"]
