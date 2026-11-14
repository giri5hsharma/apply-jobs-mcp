"""Open all approved application postings as tabs in the logged-in profile.

Uses the same persistent Firefox profile as open_application, so the session
you logged into (cookies) is reused. Tabs are opened, the process stays alive
(the browser must not be closed by the script while you click Apply).

CLI:
    .venv/bin/python -m apply_jobs_mcp.launcher [--include-review]
    .venv/bin/python -m apply_jobs_mcp.launcher --app 3 --app 4          # open specific apps
    .venv/bin/python -m apply_jobs_mcp.launcher --app 3 --fill           # auto-fill too
"""
from __future__ import annotations

import argparse
import time

from .config import Config
from .browser import BrowserSession
from .storage import Store


def approved_apps(store: Store, include_review: bool = False) -> list[dict]:
    """Applications whose job verdict allows applying (eligible; +review opt-in)."""
    out = []
    for app in store.list_applications():
        job = app.get("job_snapshot") or {}
        if job.get("status") == "eligible" or (include_review and job.get("status") == "needs_review"):
            out.append({"url": job.get("url", ""), "title": job.get("title", ""),
                        "employer": job.get("employer", ""), "app_id": app["id"]})
    return out


def _cover_text(app: dict) -> str:
    try:
        from pathlib import Path

        p = Path(app.get("cover_letter", ""))
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        return ""


def open_all(cfg: Config, urls: list[str]) -> None:
    with BrowserSession(cfg) as bs:
        for i, url in enumerate(urls):
            if i == 0:
                bs.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            else:
                page = bs._ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        print(f"OPENED {len(urls)} tabs", flush=True)
        while True:  # keep the browser alive for manual Apply clicks
            time.sleep(30)


def open_and_fill(cfg: Config, app_id: int, wait_secs: int = 150) -> None:
    """Open one application and keep trying to fill it (handles login/modals)."""
    from pathlib import Path

    store = Store(cfg.data_dir / "applications.sqlite3")
    app = store.get_application(app_id)
    store.close()
    if not app:
        print(f"no application {app_id}")
        return
    job = app.get("job_snapshot") or {}
    url = job.get("url", "")
    print(f"fill app {app_id}: {job.get('title', '')} @ {job.get('employer', '')}", flush=True)
    print("url:", url, flush=True)
    cover = _cover_text(app)
    with BrowserSession(cfg) as bs:
        bs.open_job(url)
        deadline = time.time() + wait_secs
        printed_unknowns: set = set()
        result = {"filled": []}
        while time.time() < deadline:
            try:
                result = bs.fill_known_fields(
                    app["form_answers"], app.get("resume_pdf") or "", cover_letter_text=cover
                )
            except Exception as e:
                print("fill attempt failed:", e, flush=True)
                time.sleep(8)
                continue
            if result["filled"]:
                break
            for u in result["unknown_fields"]:
                if u not in printed_unknowns and u.startswith("textarea"):
                    printed_unknowns.add(u)
            if printed_unknowns:
                print("waiting for form; unknowns so far:",
                      len(result["unknown_fields"]), flush=True)
            time.sleep(8)
        print(f"FILLED {len(result['filled'])} fields:", flush=True)
        for f in result["filled"]:
            print("  -", f["field"], "=", str(f["value"])[:50], flush=True)
        print(f"UNKNOWN ({len(result['unknown_fields'])}):", flush=True)
        for u in result["unknown_fields"]:
            print("  -", u[:70], flush=True)
        print("resume attached:", bool(result["resume_attached"]), flush=True)
        print("FILL DONE - review the window, type unknowns, then submit manually"
              " (or tell me CONFIRM)", flush=True)
        while True:
            time.sleep(30)


def main() -> None:
    p = argparse.ArgumentParser(description="open approved applications in the logged-in profile")
    p.add_argument("--include-review", action="store_true",
                   help="also open needs_review jobs (review-only candidates)")
    p.add_argument("--app", type=int, action="append", default=None,
                   help="specific application id(s); opens just these")
    p.add_argument("--fill", action="store_true",
                   help="attempt to fill the form (contacts + resume + cover letter)")
    args = p.parse_args()
    cfg = Config.load()
    if args.app:
        store = Store(cfg.data_dir / "applications.sqlite3")
        apps = []
        for aid in args.app:
            app = store.get_application(aid)
            if not app:
                print(f"no application {aid}")
                continue
            job = app.get("job_snapshot") or {}
            apps.append({"url": job.get("url", ""), "title": job.get("title", ""),
                         "employer": job.get("employer", ""), "app_id": aid})
        store.close()
        if not apps:
            return
        print("opening:")
        for a in apps:
            print(f"  app {a['app_id']} | {a['title'][:40]} | {a['employer'][:16]} | {a['url']}")
        if args.fill and len(apps) == 1:
            open_and_fill(cfg, apps[0]["app_id"])
        else:
            open_all(cfg, [a["url"] for a in apps])
        return
    store = Store(cfg.data_dir / "applications.sqlite3")
    apps = approved_apps(store, include_review=args.include_review)
    if not apps:
        print("no approved applications yet (run apply_batch / prepare_application first)")
        return
    print("approved apps:")
    for a in apps:
        print(f"  app {a['app_id']} | {a['title'][:40]} | {a['employer'][:16]} | {a['url']}")
    open_all(cfg, [a["url"] for a in apps])


if __name__ == "__main__":
    main()
