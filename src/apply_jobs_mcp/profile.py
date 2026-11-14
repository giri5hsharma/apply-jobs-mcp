"""Parse the canonical LaTeX resume (cv.tex) into a Profile.

Learning notes:
- We parse the .tex, not the PDF: text, dates, and links survive losslessly.
- A tiny brace-depth scanner replaces fragile regexes: LaTeX nests braces
  (e.g. \\href{url}{\\textbf{PR \\#934}}), so we track brace depth instead of
  matching "[^}]*".
- Only the canonical file is read. Output always goes elsewhere - the source
  resume is never written.
"""
from __future__ import annotations

import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import Contact, Education, Entry, Experience, Profile, Project

# Order matters: \\textasciitilde contains ~, so it must convert first.
_ESCAPES = [
    (r"\textasciitilde", "~"),
    (r"\textless", "<"),
    (r"\%", "%"),
    (r"\&", "&"),
    (r"\#", "#"),
    (r"$\times$", "×"),
    (r"$|$", "|"),
    (r"~", " "),
]

_SECTION_RE = re.compile(r"\\section\{([^{}]*)\}")
_COURSEWORK_RE = re.compile(r"\\item\s+(.*)$")
_FA_RE = re.compile(r"\\fa[A-Za-z]+")
_NAME_RE = re.compile(r"\\textbf\{([A-Za-z ]+)\}")


def _unescape(s: str) -> str:
    for k, v in _ESCAPES:
        s = s.replace(k, v)
    return s


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Given text[start] == '{', return (contents, index after closing '}')."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    raise ValueError(f"unbalanced braces at offset {start}")


def _decode(s: str) -> Entry:
    """Decode LaTeX formatting inside one block into plain text + metadata.

    Handles: \\textbf, \\textit, \\small, \\href, \\vspace, \\fa*, escapes.
    """
    text, bold, italic, link = "", [], [], None
    i = 0
    _CHAR_ESCAPES = {
        "textasciitilde": "~",
        "textless": "<",
        "%": "%",
        "&": "&",
        "#": "#",
    }
    while i < len(s):
        tail = s[i:]
        m = re.match(r"\\(textbf|textit|small)\{", tail)
        if m:
            body, end = _balanced(s, i + m.span()[1] - 1)
            inner = _decode(body)
            text += inner.text
            bold += inner.bold
            italic += inner.italic
            if link is None:
                link = inner.link
            if m.group(1) == "textbf":
                bold.append(inner.text)
            elif m.group(1) == "textit":
                italic.append(inner.text)
            i = end
            continue
        m = re.match(r"\\href\{([^{}]*)\}\{", tail)
        if m:
            body, end = _balanced(s, i + m.span()[1] - 1)
            inner = _decode(body)
            text += inner.text
            bold += inner.bold
            italic += inner.italic
            link = {"label": inner.text, "url": m.group(1)}
            i = end
            continue
        m = re.match(r"\\vspace\{[^{}]*\}", tail)
        if m:
            i += m.span()[1]
            continue
        if _FA_RE.match(tail):
            i += _FA_RE.match(tail).end()
            continue
        m = re.match(r"\\small|\\scshape|\\footnotesize|\\large|\\Huge|\\huge|\\tiny|\\normal", tail)
        if m and (len(tail) == m.end() or tail[m.end()] in r" \{"):
            i += m.end()
            continue
        c = s[i]
        if c == "\\":
            em = re.match(r"\\(textasciitilde|textless|%|&|#)", tail)
            if em:
                text += _CHAR_ESCAPES[em.group(1)]
                i += em.span()[1]
            else:
                i += 1
            continue
        if c == "$":
            if tail.startswith(r"$\times$"):
                text += "×"
                i += len(r"$\times$")
            elif tail.startswith(r"$|$"):
                text += "|"
                i += 3
            else:
                text += c
                i += 1
            continue
        if c in "{}":
            i += 1
        else:
            text += c
            i += 1
    return Entry(
        text=_unescape(text).strip(),
        bold=[_unescape(b) for b in bold],
        italic=[_unescape(i) for i in italic],
        link=link,
    )


def _grab_args(lines: list[str], start_line: int, n: int) -> tuple[list[str], int]:
    """Reads the next n balanced {..} arguments, possibly spanning lines.

    Returns (args, index of last consumed line).
    """
    args, depth, cur, started = [], 0, "", False
    li, ci = start_line, 0
    while li < len(lines) and len(args) < n:
        line = lines[li]
        while ci < len(line):
            c = line[ci]
            if not started:
                if c == "{":
                    started, depth, cur = True, 1, ""
                ci += 1
                continue
            if c == "{":
                depth += 1
                cur += c
            elif c == "}":
                depth -= 1
                if depth == 0:
                    args.append(cur)
                    started, cur = False, ""
                else:
                    cur += c
            else:
                cur += c
            ci += 1
        li += 1
        ci = 0
        if started and li < len(lines):
            cur += "\n"
    return args, li


_METRIC_RES = [
    re.compile(r"[~]?\d+(?:\.\d+)?[×x]\s*[A-Za-z]+"),
    re.compile(r"[<]?\s?\d+(?:\.\d+)?%"),
    re.compile(r"\d+ms"),
    re.compile(r"\d+\+\s*Solved"),
]


def _extract_metrics(texts: list[str]) -> list[str]:
    seen, out = set(), []
    for t in texts:
        for rx in _METRIC_RES:
            for m in rx.findall(t):
                if m not in seen:
                    seen.add(m)
                    out.append(m.strip())
    return out


def _split_titled(entry: Entry, separator: str = "|") -> tuple[str, str]:
    """Splits 'Name | \\textit{Tech}' style entry text into two parts."""
    if separator not in entry.text:
        return entry.text, ""
    left, right = entry.text.split(separator, 1)
    return left.strip(), right.strip()


def _split_commas(s: str) -> list[str]:
    """Split on commas, but never inside parentheses, e.g. 'AWS (EC2, RDS)'."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def load_profile(tex_path: str | Path) -> Profile:
    if Path(tex_path).suffix.lower() == ".pdf":
        return _load_pdf_profile(Path(tex_path))
    src = Path(tex_path).read_text(encoding="utf-8")
    body = src.split("\\begin{document}", 1)[1] if "\\begin{document}" in src else src
    body = re.sub(r"^\s*%.*$", "", body, flags=re.M)
    lines = body.splitlines()

    profile = Profile(source=str(tex_path))
    section = ""
    edu: Education | None = None
    current_block: object = profile

    def collect_entry(entry: Entry) -> None:
        text_of = entry.text + " " + " ".join(entry.bold)
        profile.metrics.extend(_extract_metrics([text_of]))
        if isinstance(current_block, Experience):
            current_block.entries.append(entry)
        elif isinstance(current_block, Project):
            current_block.entries.append(entry)

    i = 0
    while i < len(lines):
        line = lines[i]
        sm = _SECTION_RE.search(line)
        if sm:
            section = _unescape(sm.group(1))
            current_block = profile
            if section == "Education":
                edu = Education()
                profile.education.append(edu)
            i += 1
            continue

        if section == "" and "\\href{" in line:
            for hm in re.finditer(r"\\href\{([^{}]*)\}\{", line):
                url = hm.group(1)
                body, _ = _balanced(line, hm.span()[1] - 1)
                entry = _decode(body)
                label = entry.text.strip()
                if url.startswith("mailto:"):
                    profile.contact.emails.append(label or url[len("mailto:"):])
                elif url.startswith("tel:"):
                    profile.contact.phones.append(label or url[len("tel:"):])
                else:
                    profile.contact.links.append({"label": label, "url": url})
                profile.metrics.extend(_extract_metrics([label]))

        if "\\resumeHeading" in line:
            args, i = _grab_args(lines, i, 4)
            if len(args) < 4:
                i += 1
                continue
            decoded = [_decode(a) for a in args]
            if section == "Education" and edu is not None:
                edu.institution = decoded[0].text
                edu.dates = decoded[1].text
                edu.degree = decoded[2].text
                edu.location = decoded[3].text
                m = re.search(r"CGPA:?\s*([\d.]+)", edu.degree)
                if m:
                    edu.cgpa = float(m.group(1))
                edu.degree = re.sub(r"\s*\(CGPA:?[^)]*\)", "", edu.degree).strip()
            elif section == "Work & Open Source Experience":
                exp = Experience()
                exp.organization, exp.tagline = _split_titled(decoded[0])
                exp.dates = decoded[1].text
                exp.role = decoded[2].text
                exp.location = decoded[3].text
                profile.open_source.append(exp)
                current_block = exp
            elif section == "Projects":
                proj = Project()
                proj.name, proj.tech = _split_titled(decoded[0])
                proj.dates = decoded[1].text
                proj.role = decoded[2].text
                if decoded[3].link:
                    proj.link = decoded[3].link
                profile.projects.append(proj)
                current_block = proj
            continue

        if section == "Skills" and "\\small{" in line:
            args, i = _grab_args(lines, i, 1)
            content = args[0] if args else ""
            content = content.removeprefix("\\item{").removesuffix("}")
            for group in content.split(r"\\"):
                gm = re.match(r"\s*\\textbf\{([^{}]*)\}\{:([^}]*)\}", group)
                if gm:
                    profile.skills[_unescape(gm.group(1))] = [
                        s.strip()
                        for s in _split_commas(_unescape(gm.group(2)))
                        if s.strip()
                    ]
            continue

        if section == "Skills":
            i += 1
            continue

        if "\\resumeItem{" in line:
            args, _i = _grab_args(lines, i, 1)
            if args:
                collect_entry(_decode(args[0]))
            i += 1
            continue

        cm = _COURSEWORK_RE.search(line)
        if section == "Education" and cm and edu is not None:
            entry = _decode(cm.group(1))
            if "Coursework" in entry.text:
                csv = entry.text.split(":", 1)[1]
                edu.coursework = [s.strip() for s in csv.split(",") if s.strip()]
            i += 1
            continue

        nm = _NAME_RE.search(line)
        if section == "" and nm and not profile.name:
            profile.name = nm.group(1)

        i += 1

    bullets = [e for o in profile.open_source for e in o.entries] + [
        e for p in profile.projects for e in p.entries
    ]
    profile.metrics = list(
        dict.fromkeys(profile.metrics + _extract_metrics([b.text for b in bullets]))
    )
    return profile


def _pdf_text(path: Path) -> str:
    """Extract selectable PDF text; use native PDFKit on macOS if pypdf is absent."""
    try:
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except ImportError:
        if sys.platform != "darwin":
            raise RuntimeError("PDF resume support requires pypdf")
        script = ("import Foundation; import PDFKit; "
                  "let url=URL(fileURLWithPath:CommandLine.arguments.last!); "
                  "guard let pdf=PDFDocument(url:url) else { exit(1) }; "
                  "print(pdf.string ?? \"\")")
        result = subprocess.run(
            ["swift", "-e", script, str(path)], capture_output=True, text=True,
            timeout=120,
            env={**os.environ,
                 "CLANG_MODULE_CACHE_PATH": str(Path(tempfile.gettempdir()) / "ajm-clang-cache"),
                 "SWIFT_MODULE_CACHE_PATH": str(Path(tempfile.gettempdir()) / "ajm-swift-cache")},
        )
        if result.returncode:
            raise RuntimeError(f"could not read PDF resume: {result.stderr[-500:]}")
        return result.stdout


def _load_pdf_profile(path: Path) -> Profile:
    lines = [line.strip() for line in _pdf_text(path).splitlines() if line.strip()]
    if not lines:
        raise ValueError("PDF resume has no extractable text")
    profile = Profile(name=lines[0], source=str(path))
    text = "\n".join(lines)
    profile.contact.emails = list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)))
    profile.contact.phones = list(dict.fromkeys(re.findall(r"\+\d[\d ]{8,15}", text)))
    for host in ("github.com", "linkedin.com", "leetcode.com"):
        for link in re.findall(rf"(?:https?://)?{re.escape(host)}/[^\s|]+", text, re.I):
            profile.contact.links.append({"label": link, "url": "https://" + link.removeprefix("https://").removeprefix("http://")})
    headings = {"Education", "Technical Skills", "Work Experience", "Selected Projects", "Leadership & Awards"}
    sections: dict[str, list[str]] = {}
    section = "header"
    for line in lines[1:]:
        if line in headings:
            section = line
            sections[section] = []
        else:
            sections.setdefault(section, []).append(line)
    education = sections.get("Education", [])
    if education:
        first = education[0]
        dates = re.search(r"20\d{2}\s*[–-]\s*20\d{2}(?:\s*\(Expected\))?", first)
        cgpa = re.search(r"CGPA:\s*([\d.]+)", " ".join(education))
        coursework = re.search(r"Relevant Coursework:\s*(.*)", " ".join(education))
        profile.education.append(Education(
            institution=first.split(" B.Tech", 1)[0],
            degree="B.Tech" + first.split(" B.Tech", 1)[1].split(dates.group(0), 1)[0] if " B.Tech" in first and dates else first,
            dates=dates.group(0) if dates else "",
            cgpa=float(cgpa.group(1)) if cgpa else None,
            coursework=[s.strip() for s in coursework.group(1).split(",")] if coursework else [],
        ))
    for line in sections.get("Technical Skills", []):
        if ":" in line:
            group, values = line.split(":", 1)
            profile.skills[group] = [value.strip() for value in values.split(",") if value.strip()]
    for line in sections.get("Work Experience", []):
        if line.startswith("•") and profile.open_source:
            profile.open_source[-1].entries.append(Entry(text=line.lstrip("• ")))
        elif line.startswith("•"):
            continue
        elif re.search(r"\bIntern\b", line):
            profile.open_source.append(Experience(role=line))
        elif profile.open_source and not profile.open_source[-1].organization:
            profile.open_source[-1].organization = line
        elif profile.open_source and profile.open_source[-1].entries:
            profile.open_source[-1].entries[-1].text += " " + line
    for line in sections.get("Selected Projects", []):
        if line.startswith("•") and profile.projects:
            profile.projects[-1].entries.append(Entry(text=line.lstrip("• ")))
        elif line.startswith("•"):
            continue
        elif " GitHub" in line:
            profile.projects.append(Project(name=line.split(" GitHub", 1)[0], dates=line.split("|", 1)[-1].strip()))
        elif profile.projects and not profile.projects[-1].tech:
            profile.projects[-1].tech = line
        elif profile.projects and profile.projects[-1].entries:
            profile.projects[-1].entries[-1].text += " " + line
    profile.metrics = _extract_metrics([line for line in lines if line.startswith("•")])
    return profile
