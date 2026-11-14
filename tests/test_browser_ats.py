"""Tests for browser field classification, Greenhouse adapter, confirm tokens."""
import json

from pathlib import Path
from typing import Any

import pytest

from apply_jobs_mcp import ats
from apply_jobs_mcp.browser import (
    BrowserError,
    BrowserSession,
    _answers_of,
    classify_input,
    looks_like_cover_letter,
    resolve_engine,
)
from apply_jobs_mcp.config import Config
from apply_jobs_mcp.server import verify_token

ROOT = Path(__file__).resolve().parent.parent
CFG = Config.load(ROOT / "config.example.toml")


def test_looks_like_cover_letter():
    assert looks_like_cover_letter({"name": "cover_letter", "id": "", "placeholder": ""})
    assert looks_like_cover_letter({"name": "", "id": "", "placeholder": "Why this company?"})
    assert looks_like_cover_letter({"name": "additional_information", "id": "", "placeholder": ""})
    assert not looks_like_cover_letter({"name": "salary_expectation", "id": "", "placeholder": ""})
    assert not looks_like_cover_letter({"name": "q_notice_period", "id": "", "placeholder": ""})


def test_resolve_engine():
    assert resolve_engine(CFG) == "firefox"  # default in config.example
    custom = Config.load(ROOT / "config.example.toml")
    custom.browser["engine"] = "chromium"
    assert resolve_engine(custom) == "chromium"
    bad = Config.load(ROOT / "config.example.toml")
    bad.browser["engine"] = "safari"
    with pytest.raises(BrowserError):
        resolve_engine(bad)


class _FakeInput:
    def __init__(self, **attrs):
        self._attrs = attrs
        self.filled = False

    def get_attribute(self, name):
        return self._attrs.get(name, None)

    def fill(self, value):
        self.filled = value


class _FakeLocator:
    def __init__(self, elements: list):
        self._elements = elements

    def count(self):
        return len(self._elements)

    def nth(self, i):
        return (self._elements or [None])[i] or _FakeInput()


class _FakePage:
    def __init__(self, inputs, textareas):
        self._inputs = inputs
        self._textareas = textareas

    def locator(self, selector):
        assert selector in ("input:visible", "textarea:visible")
        return _FakeLocator(self._inputs if "input" in selector else self._textareas)


class _FakeSession(BrowserSession):
    def __init__(self, page):
        self.cfg = {"browser": {}, "data_dir": "data"}
        self.engine = "firefox"
        self._ctx = None
        self._page = page

    @property
    def page(self):
        return self._page


def test_fill_pastes_cover_letter():
    email = _FakeInput(type="email", name="email", placeholder="")
    cover = _FakeInput(name="", id="cover_input", placeholder="")
    textarea_cover = _FakeInput(name="cover_letter", id="", placeholder="")
    textarea_notice = _FakeInput(name="notice_period", id="", placeholder="")
    session = _FakeSession(_FakePage([email, cover], [textarea_cover, textarea_notice]))
    res = session.fill_known_fields(
        {"name": "Adarsh Gupta", "email": "a@b.com", "phone": "+1", "links": []},
        resume_pdf=None,
        cover_letter_text="Dear Hiring Team, PlasmaWall 7x speedup.",
    )
    assert email.filled == "a@b.com"
    assert textarea_cover.filled.startswith("Dear Hiring Team")
    assert "cover_letter" not in " ".join(res["unknown_fields"])
    assert any("notice_period" in u for u in res["unknown_fields"])  # still manual


def test_cover_letter_textarea_not_pasted_without_text():
    ta = _FakeInput(name="cover_letter", id="", placeholder="")
    session = _FakeSession(_FakePage([], [ta]))
    res = session.fill_known_fields({"name": "x"}, resume_pdf=None, cover_letter_text=None)
    assert res["filled"] == []
    assert "textarea:cover_letter" in res["unknown_fields"]

ANSWERS = {
    "name": "Adarsh Gupta",
    "email": "adarshguptatiger2006@gmail.com",
    "phone": "+918925138693",
    "links": [
        {"label": "linkedin.com/in/adarsh-gupta-a4ba60322/", "url": "https://www.linkedin.com/in/adarsh-gupta-a4ba60322/"},
        {"label": "github.com/AdarshGuptaa", "url": "https://github.com/AdarshGuptaa"},
        {"label": "leetcode.com/u/Guptadarsh/", "url": "https://leetcode.com/u/Guptadarsh/"},
    ],
}


def test_verify_token():
    assert verify_token(7, "CONFIRM-7") is None
    assert verify_token(7, "submit-7") is not None
    assert verify_token(7, "CONFIRM-8") is not None


def test_submit_does_not_treat_redirect_as_confirmation():
    class Button:
        def count(self): return 1
        def __init__(self, page): self.page = page
        @property
        def first(self): return self
        def click(self): self.page.url = "https://example.com/login"

    class Page:
        url = "https://example.com/apply"
        def get_by_role(self, *args, **kwargs): return Button(self)
        def wait_for_timeout(self, *args): pass
        def inner_text(self, *args): return "Please log in to continue"

    result = _FakeSession(Page()).submit()
    assert result["clicked"] is True
    assert result["confirmed"] is False


def test_classify_known_fields():
    assert classify_input({"type": "email", "name": "email"}, ANSWERS) == ANSWERS["email"]
    assert classify_input({"type": "tel", "placeholder": "Phone"}, ANSWERS) == ANSWERS["phone"]
    assert classify_input({"type": "text", "name": "first_name"}, ANSWERS) == "Adarsh"
    assert classify_input({"type": "text", "name": "last-name"}, ANSWERS) == "Gupta"
    assert classify_input({"type": "url", "placeholder": "LinkedIn profile"}, ANSWERS) == ANSWERS["links"][0]["url"]


def test_classify_never_guesses():
    assert classify_input({"type": "text", "name": "salary_expectation"}, ANSWERS) is None
    assert classify_input({"type": "checkbox", "name": "agreements"}, ANSWERS) is None
    assert classify_input({"type": "email", "name": "email"}, {}) is None
    assert classify_input(None, ANSWERS) is None


def test_answers_of_profile_dict():
    profile = {
        "name": "Adarsh Gupta",
        "contact": {"emails": ["a@b.com"], "phones": ["+1"], "links": []},
    }
    a = _answers_of(profile)
    assert a["email"] == "a@b.com"
    assert a["phone"] == "+1"


GH_PAYLOAD = json.dumps({
    "title": "Rust Systems Intern",
    "location": {"name": "Remote"},
    "content": "<p>Work on <b>Rust</b> services.</p>",
    "questions": [
        {"required": True, "fields": [{"name": "first_name", "label": "First Name", "type": "text"}]},
        {"required": True, "fields": [{"name": "email", "label": "Email", "type": "email"}]},
        {"required": True, "fields": [{"name": "phone", "label": "Phone", "type": "tel"}]},
        {"required": True, "fields": [{"name": "linkedin", "label": "LinkedIn URL", "type": "url"}]},
        {"required": True, "question": "What is your notice period?", "fields": [{"name": "q_notice", "label": "Notice period", "type": "single_select"}]},
        {"required": False, "question": "Anything else?", "fields": [{"name": "q_more", "label": "Message", "type": "paragraph"}]},
    ],
})


def test_greenhouse_fetch(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.ats.fetch_text", lambda *a, **k: GH_PAYLOAD)
    data = ats.fetch_greenhouse("acme", "234")
    assert data["title"] == "Rust Systems Intern"
    assert "Rust services" in data["description"]
    assert len(data["questions"]) == 6


def test_form_plan_auto_vs_manual(monkeypatch):
    monkeypatch.setattr("apply_jobs_mcp.ats.fetch_text", lambda *a, **k: GH_PAYLOAD)
    data = ats.fetch_greenhouse("acme", "234")
    plan = ats.build_form_plan(data, {
        "name": "Adarsh Gupta",
        "contact": {"emails": ["a@b.com"], "phones": ["+1"],
                    "links": [{"label": "linkedin.com/in/x", "url": "https://linkedin.com/in/x"}]},
    })
    assert plan["auto"]["first_name"] == "Adarsh"
    assert plan["auto"]["email"] == "a@b.com"
    assert plan["auto"]["phone"] == "+1"
    assert "linkedin" in plan["auto"]
    manual_labels = [m["label"] for m in plan["manual"]]
    assert "Notice period" in manual_labels
    assert "Message" in manual_labels
