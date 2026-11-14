"""Batch application orchestrator: prepare packages for high-scoring jobs.

Learning notes:
- "apply" here means: for every eligible job with score above the cutoff,
  build the full application package (tailored resume + PDF + cover letter).
  Actually submitting them is still gated by confirm_submission's explicit
  CONFIRM-<id> token - the batch can arrange everything; the operator decides.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .documents import make_application_package
from .storage import Store


def apply_batch(
    cfg: Config,
    store: Store,
    score_min: float = 25.0,
    allow_review: bool = False,
) -> dict[str, Any]:
    """Prepare applications for all eligible jobs with score > score_min."""
    rows = store.list_jobs(limit=20_000)
    targets = [
        j for j in rows
        if j["status"] == "eligible" and (j["role_match_score"] or 0) > score_min
    ]
    skipped_review = [
        j for j in rows
        if j["status"] == "needs_review" and (j["role_match_score"] or 0) > score_min
    ]
    results = []
    for j in targets:
        pkg = make_application_package(cfg, store, j["id"], allow_review=allow_review)
        results.append({
            "job_id": j["id"],
            "title": j["title"],
            "employer": j["employer"],
            "score": j["role_match_score"],
            "application_id": pkg.get("application_id", pkg.get("existing", {}).get("id")),
            "package": pkg.get("package"),
            "status": j["status"],
            "already_exists": "existing" in pkg,
        })
    return {
        "score_min": score_min,
        "prepared": len(results),
        "jobs": results,
        "skipped_needs_review": [j["title"] for j in skipped_review],
        "submit_tokens": [f"confirm_submission({r['application_id']}, 'CONFIRM-{r['application_id']}')"
                          for r in results],
        "note": ("packages prepared; review each then run open_application -> "
                 "fill_application -> confirm_submission with the token above. "
                 "Nothing was submitted."),
    }
