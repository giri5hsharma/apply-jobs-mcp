"""Greenhouse ATS adapter: fetch a posting + questions, build a fill plan.

Learning notes:
- Greenhouse keeps a public JSON API (boards-api.greenhouse.io), which we can
  read before the browser opens: that tells us exactly which questions the
  application will ask, so nothing gets filled blind.
- The plan separates "auto" (we know the answer from the profile) from
  "manual" (never guessed - surfaced for you to answer in the visible
  browser).
"""
from __future__ import annotations

import re
from typing import Any

from .jobs import fetch_text, strip_tags

BASE = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}{suffix}"

_TYPE_AUTO = {"email", "tel", "url", "text", "short_answer"}
_TYPE_GUESSABLE = {"single_select", "boolean", "attachment"}

_STD_FIELDS = {
    "first": "first name",
    "last": "last name",
    "email": "email",
    "phone": "phone",
    "linkedin": "linkedin url",
    "github": "github url",
}


def fetch_greenhouse(board: str, job_id: str) -> dict[str, Any]:
    payload = fetch_text(BASE.format(board=board, job_id=job_id, suffix="?questions=true"))
    import json

    data = json.loads(payload)
    questions = []
    for q in data.get("questions", []):
        for f in q.get("fields", []):
            questions.append({
                "label": f.get("label", ""),
                "type": f.get("type", ""),
                "required": bool(q.get("required")),
                "name": f.get("name", ""),
                "question": q.get("question", ""),
            })
    return {
        "title": data.get("title", ""),
        "location": data.get("location", {}).get("name", ""),
        "description": re.sub(r"\s+", " ", strip_tags(data.get("content", ""))).strip(),
        "questions": questions,
    }


def build_form_plan(payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Decide known vs manual fields for a Greenhouse application."""
    auto: dict[str, str] = {}
    manual: list[dict[str, Any]] = []
    answers = {
        "name": profile.get("name", ""),
        "email": (profile.get("contact", {}).get("emails") or [""])[0],
        "phone": (profile.get("contact", {}).get("phones") or [""])[0],
        "links": profile.get("contact", {}).get("links", []),
    }

    def answer_for(label: str, ftype: str) -> str | None:
        low = label.lower()
        if any(k in low for k in ("first", "given", "name")) and "last" not in low:
            return answers["name"].split()[0] if answers["name"] else None
        if any(k in low for k in ("last", "surname", "family")):
            parts = answers["name"].split()
            return parts[-1] if len(parts) > 1 else None
        if "email" in low:
            return answers["email"] or None
        if any(k in low for k in ("phone", "mobile", "tel")):
            return answers["phone"] or None
        if "linkedin" in low or "github" in low or "website" in low:
            for l in answers["links"]:
                if any(k in l.get("label", "").lower() for k in ("linkedin", "github")):
                    return l["url"]
        if ftype in ("text", "short_answer") and low in _STD_FIELDS.values():
            return answers["email"] or None
        return None

    for q in payload.get("questions", []):
        label = q.get("label") or q.get("question") or ""
        answer = answer_for(label, q.get("type", ""))
        if answer and q.get("type", "") in _TYPE_AUTO | {"url", "tel", "email"}:
            auto[q["name"] or label] = answer
        else:
            manual.append({"label": label, "type": q.get("type", ""),
                           "required": q.get("required", True),
                           "question": q.get("question", "")})
    return {"auto": auto, "manual": manual}
