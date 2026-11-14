"""Visible, isolated browser sessions for on-demand authenticated work.

Learning notes:
- Playwright's persistent context gives us a dedicated profile folder, so
  logins (LinkedIn, company ATS) persist for you but never touch your daily
  browser.
- The session is created ONLY when a tool asks for it (open_application).
- Field classification is a pure helper (classify_input) so it is testable
  without launching a browser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .sources import BlockedURL, validate_url


class BrowserError(Exception):
    pass


def _start_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserError(
            "playwright is not installed: pip install -e '.[browser]' && "
            "playwright install chromium"
        ) from e
    return sync_playwright().start()


def classify_input(attrs: dict[str, str] | None, answers: dict[str, Any]) -> str | None:
    """Map an input element's attributes to a profile answer, or None.

    attrs keys: type, name, placeholder, for_present (id present means a
    labelled input). Returns the value to type, never invents answers.
    """
    if not attrs:
        return None
    name = f"{attrs.get('name','')} {attrs.get('placeholder','')} {attrs.get('label','')}".lower()
    itype = (attrs.get("type") or "").lower()

    label = ""
    for l in answers.get("links", []):
        if any(k in l.get("label", "").lower() for k in ("linkedin", "github", "leetcode")):
            label = l["url"]
            break

    if itype == "email" or "email" in name:
        val = answers.get("email")
        return val if val else None
    if itype == "tel" or any(w in name for w in ("phone", "mobile", "telephone", "tel ")):
        val = answers.get("phone")
        return val if val else None
    if "first" in name or "first name" in name:
        parts = answers.get("name", "").split()
        return parts[0] if parts else None
    if "last" in name or "surname" in name:
        parts = answers.get("name", "").split()
        return parts[-1] if len(parts) > 1 else None
    if itype == "url" and any(w in name for w in ("linkedin", "github", "leetcode", "profile")):
        return label or None
    return None


_COVER_KEYWORDS = (
    "cover", "cover letter", "additional", "message to", "why", "reason for",
    "why this", "why you", "about you", "motivation", "introduction",
    "tell us", "summary", "interest", "experience with",
)


def looks_like_cover_letter(attrs: dict[str, str]) -> bool:
    """True for textareas that want a personal message (cover letter etc.)."""
    name = f"{attrs.get('name','')} {attrs.get('id','')} {attrs.get('placeholder','')}".lower()
    return any(k in name for k in _COVER_KEYWORDS)


def _answers_of(profile: dict[str, Any]) -> dict[str, Any]:
    """Accept both the 'contact' nested shape (get_profile) and the flat
    form-answers shape (application form_answers) without guessing."""
    contact = profile.get("contact", {}) if isinstance(profile.get("contact"), dict) else {}
    emails = contact.get("emails") or (
        [profile["email"]] if profile.get("email") else []
    ) or []
    phones = contact.get("phones") or (
        [profile["phone"]] if profile.get("phone") else []
    ) or []
    links = contact.get("links") or profile.get("links") or []
    return {
        "name": profile.get("name", ""),
        "email": emails[0] if emails else "",
        "phone": phones[0] if phones else "",
        "links": links,
    }


ENGINES = ("firefox", "chromium")


def resolve_engine(cfg: Config) -> str:
    """Engine for the persistent browser profile (default: firefox)."""
    engine = (cfg.browser.get("engine") or "firefox").strip().lower()
    if engine not in ENGINES:
        raise BrowserError(f"unsupported browser engine {engine!r} (use one of {ENGINES})")
    return engine


class BrowserSession:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.engine = resolve_engine(cfg)
        self._pw = None
        self._ctx = None

    @property
    def page(self):
        if self._ctx is None:
            raise BrowserError("browser session not open")
        return self._ctx.pages[-1] if self._ctx.pages else self._ctx.new_page()

    def __enter__(self) -> "BrowserSession":
        folder = Path(self.cfg.browser.get("profile_dir", "data/browser-profile"))
        folder.mkdir(parents=True, exist_ok=True)
        visible = bool(self.cfg.browser.get("visible", True))
        self._pw = _start_playwright()
        try:
            browser = getattr(self._pw, self.engine)
            self._ctx = browser.launch_persistent_context(
                str(folder), headless=not visible, accept_downloads=True
            )
            def guard_navigation(route):
                if route.request.is_navigation_request():
                    try:
                        validate_url(route.request.url)
                    except BlockedURL:
                        route.abort()
                        return
                route.continue_()
            self._ctx.route("**/*", guard_navigation)
            return self
        except Exception as e:
            if self._pw:
                self._pw.stop()
                self._pw = None
            raise BrowserError(
                f"could not start {self.engine}: {e} "
                f"(run: .venv/bin/playwright install {self.engine})"
            ) from e

    def __exit__(self, *exc) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            pass
        finally:
            if self._pw:
                self._pw.stop()
            self._ctx = None
            self._pw = None

    # ---- actions ----

    def open_job(self, url: str) -> dict[str, Any]:
        validate_url(url)
        self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        validate_url(self.page.url)
        return {"url": self.page.url, "title": self.page.title()}

    def fill_known_fields(
        self,
        profile: dict[str, Any],
        resume_pdf: str | None = None,
        cover_letter_text: str | None = None,
    ) -> dict[str, Any]:
        """Type profile answers into fields we recognise; never guess others.

        resume_pdf: explicit path to the compiled resume for this application.
        cover_letter_text: if given, paste into cover-letter-like textareas.
        """
        answers = _answers_of(profile)
        filled, unknowns = [], []
        resume_path = None
        inputs = self.page.locator("input:visible")
        for i in range(inputs.count()):
            try:
                el = inputs.nth(i)
                attrs = {
                    "type": (el.get_attribute("type") or ""),
                    "name": (el.get_attribute("name") or ""),
                    "placeholder": (el.get_attribute("placeholder") or ""),
                    "label": "",
                }
            except Exception:
                break  # page navigated away mid-scan
            itype = attrs["type"]
            if itype == "file":
                attached = self._attach_resume(el, resume_pdf or str(self.cfg.data_dir / "resume.pdf"))
                if attached:
                    resume_path = attached
                    filled.append({"field": "resume", "value": attached})
                continue
            value = classify_input(attrs, answers)
            if value:
                try:
                    el.fill(value)
                    filled.append({"field": attrs["name"] or itype, "value": value})
                except Exception:
                    unknowns.append(attrs["name"] or itype or itype)
                    continue
                continue
            if itype in ("checkbox", "radio", "range", "color", "hidden"):
                unknowns.append(f"{itype}:{attrs['name'] or 'unnamed'}")
            elif itype in ("text", "tel", "email", "url") and value is None:
                unknowns.append(f"text:{attrs['name'] or attrs['placeholder'] or 'unnamed'}")

        for i in range(self.page.locator("textarea:visible").count()):
            try:
                el = self.page.locator("textarea:visible").nth(i)
                attrs = {
                    "name": el.get_attribute("name") or "",
                    "id": el.get_attribute("id") or "",
                    "placeholder": el.get_attribute("placeholder") or "",
                }
            except Exception:
                break
            if cover_letter_text and looks_like_cover_letter(attrs):
                try:
                    el.fill(cover_letter_text[:1500])
                    filled.append({"field": "cover_letter",
                                   "value": cover_letter_text[:60]})
                    continue
                except Exception:
                    pass
            unknowns.append(f"textarea:{attrs['name'] or attrs['placeholder'] or 'textarea'}")

        return {
            "filled": filled,
            "unknown_fields": unknowns,
            "resume_attached": resume_path,
            "verdict": "pause: review unknowns/manual questions",
        }

    def _attach_resume(self, el: Any, candidate: str) -> str | None:
        target = Path(candidate)
        if not target.exists():
            return None
        try:
            el.set_input_files(str(target))
            return str(target)
        except Exception:
            return None

    def submit(self) -> dict[str, Any]:
        """Click the submit action AFTER explicit confirmation. Records result."""
        import re

        before = self.page.url
        clicked = False
        for text in ("Submit Application", "Submit"):
            btn = self.page.get_by_role("button", name=re.compile(text, re.I))
            if btn.count() > 0:
                btn.first.click()
                clicked = True
                break
        if not clicked:
            return {"url": before, "confirmed": False, "clicked": False,
                    "page_text": "No submit button found"}
        self.page.wait_for_timeout(4_000)
        page_text = self.page.inner_text("body")[:600]
        confirmed = bool(re.search(
            r"thank you for (?:applying|your application)|application (?:was |has been )?(?:submitted|received)|successfully applied",
            page_text, re.I))
        return {
            "url": self.page.url,
            "confirmed": confirmed,
            "clicked": True,
            "page_text": page_text,
        }
