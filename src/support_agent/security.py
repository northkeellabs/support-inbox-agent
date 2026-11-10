"""Untrusted-data wrapping, URL stripping, rule-based detectors, redaction and hashing."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+")
_BARE_DOMAIN_RE = re.compile(r"(?i)\b[a-z0-9][a-z0-9-]{0,62}(?:\.[a-z0-9-]{1,63})*\.(?:com|net|org|io|ai|co|xyz|info|biz|ru|top|click|link|example)(?:/[^\s)\]]*)?\b")
_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
# Long opaque tokens that look like API keys or bearer tokens.
_KEYLIKE_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|[A-Fa-f0-9]{32,}|[A-Za-z0-9_-]{40,})\b")
_INJECTION_RE = re.compile(
    r"(?i)(ignore (?:all |any |your )?(?:previous|prior|above) instructions|disregard (?:the |all |your )?(?:previous|prior|above)|"
    r"you are (?:now )?(?:an? )?(?:ai|assistant|agent|language model)|system prompt|hidden rules|"
    r"note (?:to|for) (?:the )?(?:ai|assistant|agent)s?|(?:ai|llm) (?:support )?assistants?:|"
    r"instructions? (?:for|to) (?:the )?(?:ai|assistant|agent|llm))"
)
# Refunds, chargebacks and money disputes: always a human decision.
_REFUND_RE = re.compile(
    r"(?i)\b(refund(?:ed|s)?|money back|charge ?back|dispute[sd]?|double[- ]charged|charged twice|"
    r"overcharged|reimburse(?:ment)?)\b")
_LEGAL_RE = re.compile(
    r"(?i)\b(lawyer|attorney|solicitor|legal action|lawsuit|sue (?:you|ledgerline)|small claims|"
    r"court|trading standards|consumer protection (?:agency|authority))\b")
# A draft must never promise money, credits or dates. Matches promise-like phrasing, not neutral policy text.
_PROMISE_RE = re.compile(
    r"(?i)(\b(?:we|i)(?:'ll| will| have| can| are going to)?\s+(?:issue|process|give|grant|send|approve|apply)\w*\s+"
    r"(?:you\s+)?(?:a\s+|an\s+|the\s+|your\s+)?(?:full\s+|partial\s+)?(?:refund|credit|discount|reimbursement)|"
    r"\b(?:you are|you're|you will be) (?:entitled|eligible) to (?:a )?(?:full |partial )?(?:refund|credit)|"
    r"\b(?:full|guaranteed) refund\b|\b\d+[- ]month credit\b|\bfree months?\b)")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def wrap_untrusted(label: str, text: str, attrs: str = "") -> str:
    """Wrap outside text so the model treats it as data. Neutralise any attempt to open or close a data tag."""
    safe = re.sub(r"(?i)</?\s*(?:untrusted|kb_chunk)[^>]*>", "[tag removed]", text or "")
    a = f" {attrs}" if attrs else ""
    return f"<untrusted_{label}{a}>\n{safe}\n</untrusted_{label}>"


def looks_like_injection(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _INJECTION_RE.finditer(text or "")})


def mentions_refund_or_dispute(text: str) -> bool:
    return bool(_REFUND_RE.search(text or ""))


def mentions_legal_threat(text: str) -> bool:
    return bool(_LEGAL_RE.search(text or ""))


def promises_money(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _PROMISE_RE.finditer(text or "")})


def find_urls(text: str) -> list[str]:
    """URLs and bare domains (email addresses are not counted as domains)."""
    no_emails = _EMAIL_RE.sub(" ", text or "")
    found = _URL_RE.findall(no_emails)
    rest = _URL_RE.sub(" ", no_emails)
    return found + [m.group(0) for m in _BARE_DOMAIN_RE.finditer(rest)]


def find_emails(text: str) -> list[str]:
    return _EMAIL_RE.findall(text or "")


def strip_urls(text: str) -> str:
    """Remove every URL, bare domain and email address (used for model text that goes into CRM notes)."""
    return strip_urls_not_in(text, "")[0]


def strip_urls_not_in(text: str, allowed_text: str) -> tuple[str, list[str]]:
    """Remove URLs and bare domains (and unknown email addresses) that do not appear verbatim in allowed_text."""
    allowed = (allowed_text or "").lower()
    removed: list[str] = []

    def keep_or_drop(m: re.Match) -> str:
        u = m.group(0).rstrip(".,;:")
        tail = m.group(0)[len(u):]
        if u.lower() in allowed:
            return m.group(0)
        removed.append(u)
        return "[link removed]" + tail

    out = _EMAIL_RE.sub(keep_or_drop, text or "")
    # protect kept emails from the domain pass
    kept_emails = {e.lower() for e in _EMAIL_RE.findall(out)}
    placeholders: dict[str, str] = {}
    for i, e in enumerate(sorted(kept_emails)):
        ph = f"\x00EMAIL{i}\x00"
        placeholders[ph] = e
        out = re.sub(re.escape(e), ph, out, flags=re.I)
    out = _URL_RE.sub(keep_or_drop, out)
    out = _BARE_DOMAIN_RE.sub(keep_or_drop, out)
    for ph, e in placeholders.items():
        out = out.replace(ph, e)
    return out, removed


def redact(value: Any, secrets: Iterable[str] = ()) -> Any:
    """Recursively redact known secrets and key-like tokens from strings in a structure."""
    secrets = list(secrets)
    if isinstance(value, str):
        out = value
        for s in secrets:
            if s and len(s) >= 6:
                out = out.replace(s, "[REDACTED]")
        return _KEYLIKE_RE.sub("[REDACTED]", out)
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    return value
