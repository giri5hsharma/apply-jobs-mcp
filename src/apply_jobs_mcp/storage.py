"""SQLite persistence for jobs, applications, and events.

Learning notes:
- WAL mode lets the scheduled worker and the MCP server open the same file
  concurrently. sqlite3 + json columns keep it a zero-dependency store.
- Every row is returned as a dict; repeated write/read keeps the API tiny.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  source_id TEXT NOT NULL DEFAULT '',
  employer TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  remote INTEGER NOT NULL DEFAULT 0,
  job_id TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  compensation_raw TEXT NOT NULL DEFAULT '',
  compensation_inr_monthly REAL,
  currency TEXT NOT NULL DEFAULT '',
  visa_support TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'discovered',
  reasons TEXT NOT NULL DEFAULT '[]',
  role_match_score REAL NOT NULL DEFAULT 0,
  discovered_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  campaign_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'prepared',
  policy_snapshot TEXT NOT NULL DEFAULT '{}',
  job_snapshot TEXT NOT NULL DEFAULT '{}',
  resume_tex TEXT NOT NULL DEFAULT '',
  resume_pdf TEXT NOT NULL DEFAULT '',
  cover_letter TEXT NOT NULL DEFAULT '',
  form_answers TEXT NOT NULL DEFAULT '{}',
  submitted_at TEXT NOT NULL DEFAULT '',
  confirmation TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _d(value: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


class Store:
    def __init__(self, path: str | Path | sqlite3.Connection):
        if isinstance(path, sqlite3.Connection):
            self.conn = path
        else:
            self.path = str(path)
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _row(self, cur: sqlite3.Cursor) -> dict | None:
        row = cur.fetchone()
        return dict(row) if row else None

    # ---- jobs ----

    def add_job(self, job: dict[str, Any]) -> int:
        """Insert a job; if the URL exists, update it and return its id."""
        now = _now()
        cur = self.conn.execute(
            """
            INSERT INTO jobs (url, source_id, employer, title, location, remote,
                              job_id, description, compensation_raw,
                              compensation_inr_monthly, currency, visa_support,
                              status, reasons, role_match_score, discovered_at,
                              updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              employer=excluded.employer, title=excluded.title,
              location=excluded.location, remote=excluded.remote,
              description=excluded.description,
              compensation_raw=excluded.compensation_raw,
              compensation_inr_monthly=excluded.compensation_inr_monthly,
              currency=excluded.currency, visa_support=excluded.visa_support,
              status=excluded.status, reasons=excluded.reasons,
              role_match_score=excluded.role_match_score, updated_at=excluded.updated_at
            """,
            (
                job["url"],
                job.get("source_id", ""),
                job.get("employer", ""),
                job.get("title", ""),
                job.get("location", ""),
                1 if job.get("remote") else 0,
                job.get("job_id", ""),
                job.get("description", ""),
                job.get("compensation_raw", ""),
                job.get("compensation_inr_monthly"),
                job.get("currency", ""),
                job.get("visa_support", ""),
                job.get("status", "discovered"),
                _j(job.get("reasons", [])),
                job.get("role_match_score", 0.0),
                now,
                now,
            ),
        )
        self.conn.commit()
        return cur.lastrowid or self.job_id_for_url(job["url"])

    def job_id_for_url(self, url: str) -> int | None:
        row = self._row(self.conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)))
        return row["id"] if row else None

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self._row(self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)))
        if row:
            row["remote"] = bool(row["remote"])
            row["reasons"] = _d(row["reasons"])
        return row

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        for k in list(fields):
            if isinstance(fields[k], (dict, list)):
                fields[k] = _j(fields[k])
        sets = ", ".join(f"{k}=?" for k in fields)
        values = [fields[k] for k in fields] + [_now(), job_id]
        self.conn.execute(
            f"UPDATE jobs SET {sets}, updated_at=? WHERE id=?", values
        )
        self.conn.commit()

    def list_jobs(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY role_match_score DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs ORDER BY role_match_score DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._normalize_job(dict(r)) for r in rows]

    @staticmethod
    def _normalize_job(row: dict[str, Any]) -> dict[str, Any]:
        row["remote"] = bool(row["remote"])
        row["reasons"] = _d(row["reasons"])
        return row

    def application_by_job(self, job_id: int) -> dict[str, Any] | None:
        row = self._row(
            self.conn.execute(
                "SELECT id FROM applications WHERE job_id=? ORDER BY id DESC LIMIT 1",
                (job_id,),
            )
        )
        return self.get_application(row["id"]) if row else None

    def next_application_id(self) -> int:
        row = self._row(
            self.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM applications")
        )
        return int(row["n"])

    # ---- applications ----

    def add_application(self, app: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO applications (job_id, campaign_id, status, policy_snapshot,
                                      job_snapshot, resume_tex, resume_pdf,
                                      cover_letter, form_answers, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                app["job_id"],
                app.get("campaign_id", ""),
                app.get("status", "prepared"),
                _j(app.get("policy_snapshot", {})),
                _j(app.get("job_snapshot", {})),
                app.get("resume_tex", ""),
                app.get("resume_pdf", ""),
                app.get("cover_letter", ""),
                _j(app.get("form_answers", {})),
                _now(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_application(self, app_id: int, **fields: Any) -> None:
        if not fields:
            return
        for k in list(fields):
            if isinstance(fields[k], (dict, list)):
                fields[k] = _j(fields[k])
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE applications SET {sets} WHERE id=?", [*fields.values(), app_id])
        self.conn.commit()

    def get_application(self, app_id: int) -> dict[str, Any] | None:
        row = self._row(
            self.conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        )
        if row:
            for key in ("policy_snapshot", "job_snapshot", "form_answers"):
                row[key] = _d(row[key])
        return row

    def list_applications(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM applications WHERE status=? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM applications ORDER BY id").fetchall()
        out = []
        for r in rows:
            row = dict(r)
            for key in ("policy_snapshot", "job_snapshot", "form_answers"):
                row[key] = _d(row[key])
            out.append(row)
        return out

    # ---- events ----

    def add_event(self, kind: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events (at, kind, detail) VALUES (?,?,?)",
            (_now(), kind, detail),
        )
        self.conn.commit()

    def events(self, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
