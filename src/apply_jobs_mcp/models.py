"""Shared data models for apply-jobs-mcp.

Learning notes:
- dataclasses give us typed, self-documenting records with no heavy framework.
- to_dict() (asdict) lets us serialize to JSON for reports and MCP responses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Contact:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Education:
    institution: str = ""
    degree: str = ""
    dates: str = ""
    location: str = ""
    cgpa: float | None = None
    coursework: list[str] = field(default_factory=list)


@dataclass
class Entry:
    """One bullet (resumeItem) or link: plain text + highlighting + link."""

    text: str = ""
    bold: list[str] = field(default_factory=list)
    italic: list[str] = field(default_factory=list)
    link: dict[str, str] | None = None


@dataclass
class Experience:
    """A resumeHeading block (open-source section)."""

    organization: str = ""
    tagline: str = ""
    dates: str = ""
    role: str = ""
    location: str = ""
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Project:
    name: str = ""
    tech: str = ""
    dates: str = ""
    role: str = ""
    link: dict[str, str] | None = None
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Profile:
    name: str = ""
    contact: Contact = field(default_factory=Contact)
    education: list[Education] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    open_source: list[Experience] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
