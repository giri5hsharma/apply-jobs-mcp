"""Parse and normalize compensation text into INR per month.

Learning notes:
- Paid amounts appear from Indian stipends ("Rs 25k/month") to foreign
  salaries ("$80,000/yr"). We normalize everything to INR per month so the
  campaign thresholds are comparable across all of them.
- The parser is conservative: ranges use the lower bound; a missing or
  unparseable amount yields None (unknown), never a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CURRENCY = {
    "₹": "INR", "rs": "INR", "inr": "INR",
    "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP", "€": "EUR", "eur": "EUR",
}

_NUMBER_RE = re.compile(
    r"(?P<num>\d[\d,\.]*)\s*(?P<suf>k|lakh|lac|cr|crore|m|l|million|thousand)?",
    re.I,
)
_RANGE_RE = re.compile(
    r"(?P<a>\d[\d,\.]*)\s*(?P<asuf>k|m|l|c|lakh|lac|cr|crore|million|thousand)?\s*[-–—]\s*"
    r"(?P<b>\d[\d,\.]*)\s*(?P<bsuf>k|m|l|c|lakh|lac|cr|crore|million|thousand)?",
    re.I,
)
_ANNUAL_RE = re.compile(r"per\s*annum|per\s*year|annual|/year|/yr|\blpa\b", re.I)
_HOURLY_RE = re.compile(r"per\s*hour|hourly|/hr|/hour", re.I)

_WORD_MULT = {
    "k": 1_000, "lakh": 100_000, "lac": 100_000, "cr": 10_000_000,
    "crore": 10_000_000, "m": 1_000_000, "million": 1_000_000,
    "l": 100_000, "thousand": 1_000,
}


def _value(num: str, suffix: str | None) -> float:
    return float(num.replace(",", "")) * _WORD_MULT.get((suffix or "").lower(), 1)


def _first_amount(text: str) -> float | None:
    """First numeric amount; ranges return the LOWER bound, K/lakh aware."""
    m = _RANGE_RE.search(text)
    if m:
        v_a = _value(m["a"], m["asuf"] or m["bsuf"])
        v_b = _value(m["b"], m["bsuf"] or m["asuf"])
        return min(v_a, v_b)
    m = _NUMBER_RE.search(text)
    if not m:
        return None
    return _value(m["num"], m["suf"])


def _per_month_multiplier(text: str) -> tuple[float, str]:
    """(multiplier, kind) to convert the stated amount into per-month."""
    if _HOURLY_RE.search(text):
        return 8 * 21, "hourly"
    if _ANNUAL_RE.search(text):
        return 1 / 12, "annual"
    return 1.0, "monthly"


@dataclass
class Compensation:
    per_month_inr: float | None
    original: str
    currency: str
    note: str = ""


def parse_compensation(text: str | None, usd_to_inr: float | None = None) -> Compensation:
    """Parse a compensation string into INR/month.

    Unknown currency or no number yields per_month_inr=None (see note).
    """
    if not text:
        return Compensation(None, "", "", "no compensation text")
    t = text.strip()
    if re.search(r"unpaid|no\s*stipend|without\s*pay", t, re.I):
        return Compensation(0.0, t, "INR", "explicitly unpaid")
    if re.search(r"competitive|negotiable|on\s*request|not\s*disclosed", t, re.I):
        return Compensation(None, t, "", "amount not disclosed")

    currency = "INR"
    for sym, code in _CURRENCY.items():
        if sym in t.lower():
            currency = code
            break

    amount = _first_amount(t)
    if amount is None or amount <= 0:
        return Compensation(None, t, currency, "no number found")

    mult, kind = _per_month_multiplier(t)
    per_month_original = round(amount * mult, 2)
    note = f"parsed {amount:g} ({kind}) -> original per month {per_month_original:g}"

    if currency == "INR":
        return Compensation(per_month_original, t, currency, note)
    if currency == "USD":
        rate = usd_to_inr or 84.0
        return Compensation(round(per_month_original * rate, 2), t, currency, note)
    return Compensation(None, t, currency, f"{currency} conversion unsupported; add a rate")
