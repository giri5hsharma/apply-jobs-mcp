"""Job ingestion: from URL, saved file, or a public source scan.

Learning notes:
- Policy decides (policy.evaluate), storage persists, and everything is
  logged as an event. This module only orchestrates.
- Public scans use urllib (stdlib): no async frameworks, no Selenium for the
  sources that return plain HTML/JSON. Browser-only sources wait for the
  manual browsing step.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .adapters import scan_ashby, scan_greenhouse
from .config import Config
from .httpio import fetch_text, strip_tags
from .policy import evaluate
from .sources import BlockedURL, find_source, validate_url
from .storage import Store


def ingest_job(
    cfg: Config,
    store: Store,
    job: dict[str, Any],
    usd_to_inr: float | None = None,
) -> dict[str, Any]:
    """Validate, grade, and store one job. Returns the stored row."""
    url = job.get("url", "")
    if not url:
        raise ValueError("job url is required")
    try:
        job["source_id"] = validate_url(url)
    except BlockedURL as e:
        store.add_event("blocked", e.reason)
        return {"url": url, "status": "blocked", "blocked": e.reason}

    verdict = evaluate(job, cfg.campaign, usd_to_inr)
    job["status"] = verdict["status"]
    job["reasons"] = verdict["reasons"]
    job["role_match_score"] = verdict["score"]
    job_id = store.add_job(job)
    store.add_event("ingest", f"{job['status']}: {url}")
    return store.get_job(job_id)


def ingest_from_file(cfg: Config, store: Store, path: str | Path) -> list[dict[str, Any]]:
    """Read a saved posting (txt/md/json) and ingest as manual source."""
    path = Path(path).expanduser()
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        import json

        payload = json.loads(raw)
        jobs = payload if isinstance(payload, list) else [payload]
    else:
        lines = raw.splitlines()
        url = next((l.split()[0] for l in lines if "http" in l), "")
        if not url:
            raise ValueError("no URL found in saved posting file")
        jobs = [{"url": url, "description": raw}]
    out = []
    for jdict in jobs:
        jdict.setdefault("source_id", find_source(jdict["url"]) or "manual")
        out.append(ingest_job(cfg, store, jdict))
    return out


# ---------- public source adapters (best-effort, tested via fixtures) ----------

def _parse_internshala_cards(page: str) -> list[dict[str, Any]]:
    cards = re.split(r'id="individual_internship_(\d+)"', page)[1:]
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job_id, rest in zip(cards[0::2], cards[1::2]):
        if not job_id:
            continue
        block = re.split(r'<div class="container-fluid individual_internship', rest, maxsplit=1)[0]
        m = re.search(r"data-href='([^']+)'", block)
        link = m.group(1) if m else ""
        title = "Software Intern"
        t = re.search(r'class="job-title-href"[^>]*>\s*([^<]+)', block)
        if t:
            title = strip_tags(t.group(1)).strip()
        company = ""
        c = re.search(r'<p class="company-name">\s*([^<]+)', block)
        if c:
            company = strip_tags(c.group(1)).strip()
        location = ""
        l = re.search(r'row-1-item locations[\s\S]{0,300}?<a>\s*([^<]+)</a>\s*(?:\(([^)]+)\))?', block)
        if l:
            location = strip_tags(l.group(1)).strip()
            if l.group(2):
                location += f" ({strip_tags(l.group(2))})"
        stipend = ""
        s = re.search(r"<span class=['\"]stipend['\"]>\s*([^<]+)", block)
        if s:
            stipend = strip_tags(s.group(1)).strip()
        url = link if link.startswith("http") else f"https://internshala.com{link}"
        if url in seen:
            continue
        seen.add(url)
        jobs.append({
            "url": url,
            "job_id": job_id,
            "source_id": "internshala",
            "title": title,
            "employer": company,
            "location": location,
            "compensation_raw": stipend,
        })
    return jobs


def scan_internshala(kw: str = "software") -> list[dict[str, Any]]:
    from urllib.parse import urlencode

    if kw.strip().lower() in ("intern", "internship") or "software" in kw.lower():
        return scan_internshala_category("software-development")
    page = fetch_text("https://internshala.com/internships/?" + urlencode({"keywords": kw}))
    words = [word.lower() for word in kw.split() if word]
    return [job for job in _parse_internshala_cards(page)
            if all(word in job["title"].lower() for word in words)]


def scan_internshala_category(category: str) -> list[dict[str, Any]]:
    """Scan a category page, e.g. 'software-development' - contains real SWE roles."""
    page = fetch_text(f"https://internshala.com/internships/{category}-internship/")
    return _parse_internshala_cards(page)


def scan_amazon(kw: str = "intern", country: str = "IND") -> list[dict[str, Any]]:
    from urllib.parse import urlencode

    url = ("https://www.amazon.jobs/en/search.json?" + urlencode(
        {"base_query": kw, "country": country, "offset": 0, "result_limit": 100}))
    import json

    payload = json.loads(fetch_text(url))
    out = []
    for it in payload.get("jobs", []):
        out.append({
            "url": it.get("job_path", ""),
            "job_id": str(it.get("id", "")),
            "source_id": "amazon",
            "title": it.get("title", ""),
            "employer": "Amazon",
            "location": it.get("normalized_location", ""),
            "description": re.sub(r"<[^>]+>", " ", it.get("description", "")),
            "compensation_raw": it.get("compensation", ""),
        })
    out = [j for j in out if j["url"]]
    for j in out:
        if j["url"].startswith("/"):
            j["url"] = "https://www.amazon.jobs" + j["url"]
    return out


SCANNERS = {
    "internshala": scan_internshala,
    "amazon": scan_amazon,
    "greenhouse": scan_greenhouse,
    "ashby": scan_ashby,
}


def public_scan(cfg: Config, store: Store, source_id: str, keywords: str = "intern") -> list[dict[str, Any]]:
    """Scan one public source, grade + store each job. Returns stored rows."""
    scanner = SCANNERS.get(source_id)
    if scanner is None:
        raise ValueError(f"no public scanner for {source_id!r}; it needs on-demand browsing")
    found = scanner(keywords)
    store.add_event("scan", f"{source_id}: found {len(found)}")
    rows = []
    for j in found:
        try:
            rows.append(ingest_job(cfg, store, j))
        except Exception as e:  # keep scanning even if one listing is broken
            store.add_event("scan_error", f"{source_id}: {e}")
    return rows
