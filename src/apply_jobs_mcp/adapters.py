"""Public ATS board scanners (Greenhouse, Ashby). All official public APIs.

Every URL produced by these adapters points back at the vendor's own job
page (job-boards.greenhouse.io / jobs.ashbyhq.com), which are registered in
the sources allowlist - so the whole ingest pipeline still applies.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .httpio import fetch_text, strip_tags

# Curated, live-verified board tokens (Aug 2026). Add more by appending here.
GREENHOUSE_BOARDS = [
    "vercel", "stripe", "reddit", "cloudflare", "mozilla", "datadog",
    "duolingo", "discord", "netlify",
]
ASHBY_BOARDS = ["openai", "linear", "cursor", "perplexity", "n8n"]


def _pack(payload: dict[str, Any], size: int) -> list[dict[str, Any]]:
    return json.loads(payload) if isinstance(payload, str) else payload


def scan_greenhouse(keywords: str | None = None) -> list[dict[str, Any]]:
    """Scan every verified greenhouse board. Returns normalized job dicts."""
    out: list[dict[str, Any]] = []
    for token in GREENHOUSE_BOARDS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        board = scan_greenhouse_board(token, url)
        if keywords:
            board = [job for job in board if keywords.lower() in job["title"].lower()]
        out.extend(board)
    return out


def scan_greenhouse_board(token: str, url: str) -> list[dict[str, Any]]:
    raw = fetch_text(url, timeout=60)
    data = json.loads(raw)
    out = []
    for j in data.get("jobs", []) or []:
        content_text = strip_tags(j.get("content", "") or "")
        m = re.search(r"(?:Salary|Compensation)\s*[:.]?\s*([^\n]{3,60})", content_text)
        comp = m.group(1).strip() if m else ""
        out.append({
            "url": j.get("absolute_url", ""),
            "job_id": str(j.get("id", "")),
            "source_id": "greenhouse",
            "title": j.get("title", ""),
            "employer": token,
            "location": (j.get("location", {}) or {}).get("name", ""),
            "description": content_text,
            "compensation_raw": comp,
        })
    return out


def scan_ashby(keywords: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for board in ASHBY_BOARDS:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
        raw = fetch_text(url, timeout=60)
        data = json.loads(raw)
        for j in data.get("jobs", []) or []:
            loc = (j.get("locationName") or (j.get("secondaryLocations") or [None])[0] or "")
            comp = (j.get("compensation") or {}).get("summary") or ""
            item = {
                "url": j.get("jobUrl", ""),
                "job_id": j.get("id", ""),
                "source_id": "ashby",
                "title": j.get("title", ""),
                "employer": board,
                "location": loc,
                "description": strip_tags(j.get("descriptionHtml") or j.get("descriptionPlain") or ""),
                "compensation_raw": comp,
            }
            if not keywords or keywords.lower() in item["title"].lower():
                out.append(item)
    return out
