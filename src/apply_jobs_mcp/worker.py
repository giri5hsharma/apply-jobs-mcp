"""CLI worker for scheduled/on-demand public scans (systemd timer target).

Run:  .venv/bin/python -m apply_jobs_mcp.worker [--source amazon] [--keywords english]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import Config
from .jobs import SCANNERS, public_scan
from .storage import Store


def _print_shortlist(store: Store, limit: int = 15) -> None:
    rows = store.list_jobs(limit=10_000)
    from collections import Counter

    print(f"total: {len(rows)} | " + ", ".join(f"{k}={v}" for k, v in
          sorted(Counter(j["status"] for j in rows).items())))
    cands = [j for j in rows if j["status"] in ("eligible", "needs_review")]
    print(f"\nshortlist ({len(cands)} eligible/needs-review, top {limit} by score):")
    for j in sorted(cands, key=lambda x: -x["role_match_score"])[:limit]:
        print(f"  [{j['status']:14}] score {j['role_match_score']:3.0f} | "
              f"{j['title'][:42]:42} | {j['employer'][:16]:16} | "
              f"{j['location'][:18]:18} | {j['compensation_raw'][:16]}")
    print("\nprepare with: .venv/bin/python -m apply_jobs_mcp.worker "
          "--shortlist  (then use MCP tools list_jobs/inspect_job/prepare_application)")


def main() -> None:
    p = argparse.ArgumentParser(description="apply-jobs-mcp public scan worker")
    p.add_argument("--config", default=None, help="path to config.toml")
    p.add_argument("--source", default=None, help="one source id, or 'all'")
    p.add_argument("--keywords", default="intern", help="search keywords")
    p.add_argument("--print", action="store_true", help="log rows to stdout")
    p.add_argument("--shortlist", action="store_true",
                   help="print eligible/needs-review candidates ordered by score")
    args = p.parse_args()

    cfg = Config.load(Path(args.config) if args.config else None)
    (cfg.data_dir / "browser-profile").mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "reports").mkdir(parents=True, exist_ok=True)
    store = Store(cfg.data_dir / "applications.sqlite3")
    if args.shortlist:
        _print_shortlist(store)
        return
    try:
        sources = list(SCANNERS) if args.source in (None, "all") else [args.source]
        for sid in sources:
            rows = public_scan(cfg, store, sid, args.keywords)
            if args.print:
                for r in rows:
                    print(r["status"], f'{r.get("title","")[:50]:50}', r.get("compensation_raw",""))
    finally:
        store.close()


if __name__ == "__main__":
    main()
