"""Tiny shared HTTP helpers (stdlib urllib)."""
from __future__ import annotations

import html
import re
import urllib.request

_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_TAG_RE = re.compile(r"<[^>]+>")


def fetch_text(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(25_000_000)
    return raw.decode("utf-8", errors="replace")


def strip_tags(text: str) -> str:
    return _TAG_RE.sub(" ", html.unescape(text)).replace("\xa0", " ").strip()
