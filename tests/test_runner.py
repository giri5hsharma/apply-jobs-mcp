"""Tests for the apply_batch orchestrator."""
import tempfile
from pathlib import Path

from apply_jobs_mcp.config import Config
from apply_jobs_mcp.jobs import ingest_job
from apply_jobs_mcp.runner import apply_batch
from apply_jobs_mcp.storage import Store

ROOT = Path(__file__).resolve().parent.parent
CFG = Config.load(ROOT / "config.example.toml")


def _store():
    tmp = tempfile.TemporaryDirectory()
    return tmp, Store(Path(tmp.name) / "db.sqlite3")


def _base(**kw):
    return {
        "url": "https://internshala.com/internships/detail/770/",
        "source_id": "internshala",
        "employer": "Acme",
        "title": "Software Engineer Intern",
        "location": "Bangalore",
        "description": "Rust backend intern, REST APIs, eBPF systems.",
        "compensation_raw": "Rs 40000/month",
        **kw,
    }


def test_batch_prepares_only_high_scores():
    tmp, s = _store()
    try:
        cfg = Config.load(ROOT / "config.example.toml")
        cfg.output_dir = Path(tmp.name) / "output"
        hi = ingest_job(cfg, s, _base())
        meh = ingest_job(cfg, s, _base(url="https://internshala.com/internships/detail/771/",
                                       compensation_raw="Rs 26000/month"))
        low = ingest_job(cfg, s, _base(url="https://internshala.com/internships/detail/772/",
                                       compensation_raw="Rs 9000/month"))
        out = apply_batch(cfg, s, score_min=25.0)
        # high (40k) and meh (26k) both score > 25; the 9k job scored low_compensation
        assert out["prepared"] == 2
        job_ids = {r["job_id"] for r in out["jobs"]}
        assert job_ids == {hi["id"], meh["id"]}
        assert len(out["submit_tokens"]) == 2
        assert all("CONFIRM-" in t for t in out["submit_tokens"])
        s.close()
    finally:
        tmp.cleanup()


def test_batch_never_submits():
    tmp, s = _store()
    try:
        ingest_job(CFG, s, _base(
            url="https://internshala.com/internships/detail/773/",
            description="Pay a processing fee of Rs 1000, cv123@gmail.com, Rust intern."))
        out = apply_batch(CFG, s, score_min=0)
        assert out["prepared"] == 0  # suspicious never prepared, even at score 0
        s.close()
    finally:
        tmp.cleanup()
