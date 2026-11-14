from pathlib import Path

from apply_jobs_mcp.config import Config
from apply_jobs_mcp.policy import (
    STATUS_ELIGIBLE,
    STATUS_LOW_COMP,
    STATUS_NEEDS_REVIEW,
    evaluate,
)

ROOT = Path(__file__).resolve().parent.parent


def campaign():
    return Config.load(ROOT / "config.example.toml").campaign


def job(**kw):
    base = {
        "url": "https://example.com/job/1",
        "source_id": "internshala",
        "employer": "Acme",
        "title": "Software Engineer Intern",
        "location": "Bangalore",
        "remote": False,
        "description": "Work on backend services in Python and Rust, REST APIs.",
        "compensation_raw": "Rs 30000/month",
    }
    base.update(kw)
    return base


def test_eligible_domestic():
    r = evaluate(job(), campaign())
    assert r["status"] == STATUS_ELIGIBLE
    assert r["score"] > 0


def test_below_threshold():
    r = evaluate(job(compensation_raw="Rs 10000/month"), campaign())
    assert r["status"] == STATUS_LOW_COMP


def test_unknown_compensation_review():
    r = evaluate(job(compensation_raw="Competitive salary"), campaign())
    assert r["status"] == STATUS_NEEDS_REVIEW
    assert "compensation unknown" in r["reasons"]


def test_non_internship_rejected():
    r = evaluate(job(title="Software Engineer II"), campaign())
    assert r["status"] == "poor_role_match"


def test_intern_word_buried_in_description_rejected():
    desc = ("Senior full-time product role. " + ("Internal tooling text. " * 40)
            + "As an intern last year...")
    r = evaluate(job(title="Senior Product Manager", description=desc,
                     compensation_raw="$175,000/year", location="Remote"), campaign())
    assert r["status"] == "poor_role_match"


def test_foreign_requires_visa():
    r = evaluate(
        job(compensation_raw="$2,000/month", location="New York"),
        campaign(),
        usd_to_inr=84,
    )
    assert r["status"] == STATUS_NEEDS_REVIEW
    assert any("visa" in reason for reason in r["reasons"])


def test_foreign_with_visa_eligible():
    r = evaluate(
        job(
            compensation_raw="$2,000/month",
            location="New York",
            description="Internship with visa sponsorship support. Backend Python.",
        ),
        campaign(),
        usd_to_inr=84,
    )
    assert r["status"] == STATUS_ELIGIBLE


def test_scam_money_filter():
    r = evaluate(
        job(description="Pay a training fee of Rs 2000 to confirm your offer."),
        campaign(),
    )
    assert r["status"] == "suspicious"


def test_scam_personal_email():
    r = evaluate(
        job(description="Send your resume to recruiter123@gmail.com for this internship."),
        campaign(),
    )
    assert r["status"] == "suspicious"


def test_amazon_boilerplate_not_a_scam():
    r = evaluate(
        job(description="Transform how millions pay for their everyday essentials. "
                        "Architect payment solutions that power crypto card rails "
                        "and mobile wallets."),
        campaign(),
    )
    assert r["status"] != "suspicious"


def test_negated_fee_disclaimer_not_a_scam():
    r = evaluate(
        job(description="We never ask for any registration fee before hiring. "
                        "This internship pays Rs 30000 monthly; backend Python work."),
        campaign(),
    )
    assert r["status"] == STATUS_ELIGIBLE


def test_demanded_payment_is_a_scam():
    r = evaluate(
        job(description="Hurry! Pay us a token amount of Rs 500 to reserved your "
                        "seat for this software intern role."),
        campaign(),
    )
    assert r["status"] == "suspicious"


def test_explicit_mismatched_season_needs_review():
    r = evaluate(job(description="Summer 2026 backend Python internship, Rs 40000 monthly."), campaign())
    assert r["status"] == "needs_review"
    assert "posting season differs from campaign" in r["reasons"]


def test_explicit_mismatched_graduation_needs_review():
    r = evaluate(job(description="Backend Python internship for class of 2027, Rs 40000 monthly."), campaign())
    assert r["status"] == "needs_review"
    assert "posting graduation requirement differs from campaign" in r["reasons"]


def test_non_software_intern_is_poor_match():
    r = evaluate(job(title="Human Resources Intern", description="Join the people team."), campaign())
    assert r["status"] == "poor_role_match"
