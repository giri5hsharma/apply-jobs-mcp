"""Eligibility, scam, and ranking rules.

Learning notes:
- This module is pure (no browser, no LLM): it takes a job dict + campaign
  and returns a verdict, so it is trivially testable.
- Policy is conservative: uncertain => needs_review, never silent skip and
  never auto-apply.
- Score is a ranking hint only (0-100). Stipend is weighted highest.
"""
from __future__ import annotations

import re
from typing import Any

from .compensation import parse_compensation
from .config import Campaign

STATUS_ELIGIBLE = "eligible"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_LOW_COMP = "low_compensation"
STATUS_POOR_MATCH = "poor_role_match"
STATUS_SUSPICIOUS = "suspicious"

_HARD_MONEY = [
    (r"\b(?:registration|processing|training|security)\s+(?:fee|deposit)\b", "asks for a fee/deposit"),
    (r"\btoken amount\b", "asks for a token amount"),
    (r"\bpay\w*\s*(?:us|to us|now|cash)\b[^.]{0,40}", "requires paying us"),
    (r"\b(?:money|amount|payment|deposit)\b[^.]{0,40}\b(?:us|ours)\b[^.]{0,20}",
     "asks for money before hiring"),
    (r"\b(?:bitcoin|crypto|gift cards?|upi)[^.]{0,50}\b(?:us|ours|to us|now|transfer)\b",
     "asks for crypto/gift payment"),
]
_NEGATION_RE = re.compile(
    r"never|no\s|not\s*(?:ask|require|charge)|without|don't|do not|free of charge|free to apply",
    re.I,
)
_PERSONAL_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|rediffmail)\.com")

_VISA_MARKERS = [
    "visa sponsorship", "visa support", "visa assistance", "work visa",
    "sponsorship", "relocation visa", "h1b", "work permit",
]
_SWE_TERMS = [
    "software", "engineer", "sde", "swe", "developer", "programming", "code",
    "backend", "frontend", "full-stack", "full stack", "rust", "python",
    "java", "c++", "kotlin", "swift", "api", "system", "linux", "cloud",
]


def check_scam(title: str, description: str, employer: str = "") -> list[str]:
    """Return suspicious signals (empty list = looks fine).

    Money markers only count when they look like a demand ON THE APPLICANT
    ("pay us", "registration fee"), and never when they appear inside a
    disclaimer ("we never ask for a fee") or describe the company's product
    (payment platforms, crypto services).
    """
    reasons: list[str] = []
    haystack = f"{title} {description}".lower()
    for pattern, label in _HARD_MONEY:
        for m in re.finditer(pattern, haystack):
            before = haystack[max(0, m.start() - 60):m.start()]
            if _NEGATION_RE.search(before):
                continue
            reasons.append(label)
    if _PERSONAL_EMAIL.search(haystack):
        reasons.append("uses a personal email domain")
    if description.strip() and len(description) < 20:
        reasons.append("description suspiciously short")
    if not employer and not title:
        reasons.append("no identifiable employer")
    return reasons


def _visa_ok(text: str) -> bool:
    return any(m in text.lower() for m in _VISA_MARKERS)


def evaluate(
    job: dict[str, Any], campaign: Campaign, usd_to_inr: float | None = None
) -> dict[str, Any]:
    """Decide: status, reasons, score. Mutates job with parsed compensation."""
    title = job.get("title", "")
    location = job.get("location", "")
    description = job.get("description", "")
    haystack = f"{title} {location} {description}"

    scam = check_scam(title, description, job.get("employer", ""))
    if scam:
        job["compensation_inr_monthly"] = None
        job["currency"] = ""
        return {"status": STATUS_SUSPICIOUS, "reasons": scam, "score": 0.0}

    comp = parse_compensation(job.get("compensation_raw"), usd_to_inr)
    job["compensation_inr_monthly"] = comp.per_month_inr
    job["currency"] = comp.currency
    return _score_and_status(job, campaign, comp)


def _score_and_status(
    job: dict[str, Any], campaign: Campaign, comp: Any
) -> dict[str, Any]:
    title = job.get("title", "").lower()
    haystack = f"{title} {job.get('location','')} {job.get('description','')}".lower()

    if campaign.job_type == "internship":
        # "intern" must appear in the title, URL slug, or the start of the
        # description - not buried in a long description (false positives,
        # e.g. "as an intern you..." in full-time role prose).
        from urllib.parse import urlparse
        parsed_url = urlparse(job.get("url", ""))
        url_slug = parsed_url.path.rstrip("/").split("/")[-1]
        intern_text = (f"{job.get('title','')} {url_slug} "
                       f"{(job.get('description','') or '')[:600]}").lower()
        # matches 'intern', 'internship', 'interns', 'internships' - never
        # 'internal' (e.g. "Internal tooling" prose in full-time roles)
        from_internshala = (job.get("source_id") == "internshala" and
                           (parsed_url.hostname or "").endswith("internshala.com"))
        if not from_internshala and not re.search(r"\bintern(?:ship)?s?\b", intern_text):
            reasons = ["not an internship role"]
            return {"status": STATUS_POOR_MATCH, "reasons": reasons, "score": 0.0}

    season_years = {d.year for d in (campaign.season_start, campaign.season_end) if d}
    stated_seasons = {int(year) for year in re.findall(
        r"\b(?:spring|summer|fall|autumn|winter)\s+(20\d{2})\b", haystack, re.I)}
    if season_years and stated_seasons and stated_seasons.isdisjoint(season_years):
        return {"status": STATUS_NEEDS_REVIEW,
                "reasons": ["posting season differs from campaign"], "score": 0.0}
    stated_graduation = {int(year) for year in re.findall(
        r"\b(?:graduat(?:ing|ion)|class of)\s*(?:in\s+)?(20\d{2})\b", haystack, re.I)}
    if campaign.graduation_years and stated_graduation and stated_graduation.isdisjoint(campaign.graduation_years):
        return {"status": STATUS_NEEDS_REVIEW,
                "reasons": ["posting graduation requirement differs from campaign"], "score": 0.0}

    if not any(term in title for term in _SWE_TERMS):
        reasons = ["software engineering component unclear"]
        return {"status": STATUS_POOR_MATCH, "reasons": reasons, "score": 0.0}

    if comp.per_month_inr is None:
        reasons = ["compensation unknown"]
        return {"status": STATUS_NEEDS_REVIEW, "reasons": reasons, "score": 0.0}

    foreign = comp.currency not in ("INR", "")
    threshold = (
        campaign.foreign_min_inr_monthly if foreign else campaign.domestic_min_inr_monthly
    )
    if foreign and campaign.foreign_requires_visa_support and not _visa_ok(haystack):
        reasons = ["foreign role without explicit visa support"]
        return {"status": STATUS_NEEDS_REVIEW, "reasons": reasons, "score": 0.0}
    if comp.per_month_inr < threshold:
        reasons = [f"below threshold Rs {threshold:,}/mo"]
        return {"status": STATUS_LOW_COMP, "reasons": reasons, "score": 0.0}

    role_hits = sum(1 for r in campaign.roles if r in haystack)
    fit = min(1.0, role_hits / 3)
    cap = max(threshold, campaign.domestic_min_inr_monthly * 2)
    comp_score = min(1.0, comp.per_month_inr / cap)
    loc_lower = job.get("location", "").lower()
    hub = any(h.lower() in loc_lower for h in campaign.preferred_hubs)
    score = round(100 * (0.5 * comp_score + 0.35 * fit + (0.15 if hub else 0.0)))

    reasons = ["internship role", "software engineering component present"]
    if job.get("remote"):
        reasons.append("remote")
    if hub:
        reasons.append("preferred hub")
    if foreign:
        reasons.append("foreign role with visa support")
    return {"status": STATUS_ELIGIBLE, "reasons": reasons, "score": score}
