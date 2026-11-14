from pathlib import Path

import pytest

from apply_jobs_mcp.config import Config

ROOT = Path(__file__).resolve().parent.parent


def test_loads_example_config():
    cfg = Config.load(ROOT / "config.example.toml")
    assert cfg.resume_tex.exists()
    assert cfg.schedule.get("start") == "07:00"
    assert cfg.schedule.get("timezone") == "Asia/Kolkata"
    assert cfg.browser.get("visible") is True


def test_loads_campaign_policy():
    cfg = Config.load(ROOT / "config.example.toml")
    c = cfg.campaign
    assert c.id == "summer-spring-2027"
    assert c.job_type == "internship"
    assert c.graduation_years == [2028]
    assert c.domestic_min_inr_monthly == 25000
    assert c.foreign_min_inr_monthly == 50000
    assert c.foreign_requires_visa_support is True
    assert c.max_submissions_per_day == 10
    assert c.scan_interval_days == 3
    assert str(c.season_start) == "2027-05-01"
    assert str(c.season_end) == "2027-07-31"
    assert "Bangalore" in c.preferred_hubs
    assert "internshala" in c.source_ids


def test_campaign_is_data_driven():
    c = Config.load(ROOT / "config.example.toml").campaign
    assert c.domestic_min_inr_monthly != 0
