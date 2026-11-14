"""Configuration loading: global config.toml + campaign TOML.

Learning notes:
- config.example.toml is the committed template; user overrides go in
  config.toml (gitignored).
- Campaigns are data, not code: changing thresholds/locations/roles later
  means editing a TOML file, never Python.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class Campaign:
    id: str = ""
    job_type: str = "internship"
    season_start: date | None = None
    season_end: date | None = None
    graduation_years: list[int] = field(default_factory=list)
    domestic_min_inr_monthly: int = 25000
    foreign_min_inr_monthly: int = 50000
    foreign_requires_visa_support: bool = True
    relocation_required: bool = False
    housing_required: bool = False
    remote_ok: bool = True
    max_submissions_per_day: int = 10
    scan_interval_days: int = 3
    source_ids: list[str] = field(default_factory=list)
    preferred_hubs: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    resume_tex: Path
    data_dir: Path
    output_dir: Path
    campaign_path: Path
    campaign: Campaign
    schedule: dict[str, Any] = field(default_factory=dict)
    browser: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Config":
        root = Path(config_path or (Path.cwd() / "config.toml"))
        if not root.exists():
            root = root.parent / "config.example.toml"
        raw = tomllib.loads(root.read_text(encoding="utf-8"))

        paths = raw.get("paths", {})
        resume_tex = _expand(paths.get("resume_tex", "~/Documents/resumes/resume_tex/cv.tex"))
        data_dir = _expand(paths.get("data_dir", "data"))
        output_dir = _expand(paths.get("output_dir", "output"))
        campaign_path = _expand(paths.get("campaign", "campaigns/summer-2027.toml"))

        campaign = Campaign()
        if campaign_path.exists():
            c = tomllib.loads(campaign_path.read_text(encoding="utf-8"))
            for k, v in c.items():
                if hasattr(campaign, k):
                    if k == "season_start":
                        campaign.season_start = date.fromisoformat(v)
                    elif k == "season_end":
                        campaign.season_end = date.fromisoformat(v)
                    else:
                        setattr(campaign, k, v)
            campaign.data = c

        return cls(
            resume_tex=resume_tex,
            data_dir=data_dir,
            output_dir=output_dir,
            campaign_path=campaign_path,
            campaign=campaign,
            schedule=raw.get("schedule", {}),
            browser=raw.get("browser", {}),
            llm=raw.get("llm", {}),
        )


def _expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(str(path)))
