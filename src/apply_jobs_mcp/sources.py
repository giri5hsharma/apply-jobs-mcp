"""Approved source registry + safe URL validation.

Learning notes:
- "Browse approved sites only" is enforced here, not in the browser code:
  any URL coming in is validated against this exact allowlist first.
- Exact host matches only. Company-specific ATS hosts can be added one at a
  time; wildcards like every `myworkdayjobs.com` page are never used.
- New sources are added in this file (data), not by new parse code.
"""
from __future__ import annotations

from urllib.parse import urlparse

SOURCE_ALIASES: dict[str, str] = {
    "internship": "internshala",
}

# source_id -> {"label", "domains" (exact hosts / subdomains of given host),
#               "mode": "public" (no login) or "browse" (login required)}
SOURCES: dict[str, dict[str, str | list[str]]] = {
    "internshala": {"label": "Internshala", "mode": "public",
                    "domains": ["internshala.com"]},
    "linkedin": {"label": "LinkedIn Jobs", "mode": "browse",
                 "domains": ["linkedin.com", "www.linkedin.com", "linkedin.com/jobs"]},
    "glassdoor": {"label": "Glassdoor Jobs", "mode": "browse",
                  "domains": ["glassdoor.com", "www.glassdoor.com"]},
    "google": {"label": "Google Careers", "mode": "public",
               "domains": ["careers.google.com", "www.google.com/about/careers",
                           "careers.google.com/jobs"]},
    "meta": {"label": "Meta Careers", "mode": "public",
             "domains": ["metacareers.com", "www.metacareers.com"]},
    "nvidia": {"label": "NVIDIA Careers", "mode": "public",
               "domains": ["nvidia.com/careers", "jobs.nvidia.com", "nvidia.eightfold.ai"]},
    "amazon": {"label": "Amazon Jobs", "mode": "public",
               "domains": ["amazon.jobs", "www.amazon.jobs"]},
    "jpmorgan": {"label": "JPMorgan Chase Careers", "mode": "public",
                 "domains": ["jpmorganchase.com/careers",
                             "jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience"]},
    "greenhouse": {"label": "Greenhouse ATS boards", "mode": "public",
                   "domains": ["boards.greenhouse.io", "job-boards.greenhouse.io",
                               "boards-api.greenhouse.io"]},
    "ashby": {"label": "Ashby ATS boards", "mode": "public",
              "domains": ["api.ashbyhq.com", "jobs.ashbyhq.com"]},
    "lever": {"label": "Lever ATS boards", "mode": "public",
              "domains": ["jobs.lever.co", "api.lever.co"]},
    "naukri": {"label": "Naukri", "mode": "browse",
               "domains": ["naukri.com", "www.naukri.com"]},
    "indeed": {"label": "Indeed", "mode": "browse",
               "domains": ["indeed.com", "www.indeed.com", "in.indeed.com"]},
    "wellfound": {"label": "Wellfound", "mode": "browse",
                  "domains": ["wellfound.com", "www.wellfound.com"]},
}

_SHORTENERS = {"bit.ly", "tinyurl.com", "goo.gl", "t.ly", "cutt.ly", "rb.gy", "lnk.to"}


class BlockedURL(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


def _host_of(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower()


def is_shortener(url: str) -> bool:
    return _host_of(url) in _SHORTENERS


def find_source(url: str) -> str | None:
    """Return the source_id for a URL, or None if not on the allowlist.

    Each allowlist entry is 'host' or 'host/path-prefix'. A host matches
    exactly or as a subdomain; a path prefix must also match.
    """
    p = urlparse(url)
    host = (p.hostname or "").lower().replace("www.", "")
    path = p.path or "/"
    for sid, meta in SOURCES.items():
        for entry in meta["domains"]:
            host_part, _, path_part = str(entry).lower().partition("/")
            host_part = host_part.replace("www.", "")
            if host != host_part and not host.endswith("." + host_part):
                continue
            if path_part and not path.startswith("/" + path_part):
                continue
            return sid
    return None


def validate_url(url: str) -> str:
    """Raise BlockedURL unless the URL is an approved source URL."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise BlockedURL(url, "unsupported scheme")
    if is_shortener(url):
        raise BlockedURL(url, "URL shortener")
    sid = find_source(url)
    if sid is None:
        raise BlockedURL(url, "domain or path not on the approved source allowlist")
    return sid


def normalize_source_id(source_id: str) -> str:
    return SOURCE_ALIASES.get(source_id.strip().lower(), source_id.strip().lower())


def source_ids() -> list[str]:
    return sorted(SOURCES)
