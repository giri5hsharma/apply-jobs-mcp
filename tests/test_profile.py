"""Profile extraction from the configured resume."""
from pathlib import Path

from apply_jobs_mcp.config import Config
from apply_jobs_mcp.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent


def test_pdf_profile_facts():
    cfg = Config.load(ROOT / "config.example.toml")
    profile = load_profile(cfg.resume_tex)
    assert profile.name == "Girish Sharma"
    assert "sharmagirish.grsh@gmail.com" in profile.contact.emails
    assert any("github.com/giri5hsharma" in link["url"] for link in profile.contact.links)
    assert profile.education[0].cgpa == 8.25
    assert "2028" in profile.education[0].dates
    assert "FastAPI" in profile.skills["Web & APIs"]
    assert any(exp.organization == "Samant Solutions (Remote)" for exp in profile.open_source)
    assert any(project.name.startswith("Codemia") for project in profile.projects)
