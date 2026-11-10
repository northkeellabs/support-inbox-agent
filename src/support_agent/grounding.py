"""Grounding check, in code, on every model-written draft.

Rules:
1. Citations are chunk ids in square brackets, e.g. [webhooks#2] or [webhooks#2, api-rate-limits#1].
   Every cited id must be one of the chunks retrieved for this ticket.
2. Direct quotes go in double quotes, at most 25 words, and must appear word for word
   (case and whitespace normalised) in a chunk cited right after the quote in the same paragraph.
3. A draft with zero valid citations is not allowed.
Paraphrase is fine as long as it is cited.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUOTE_WORDS = 25
_CITE_RE = re.compile(r"\[([A-Za-z0-9_.-]+#\d+(?:\.\d+)?(?:\s*[,;]\s*[A-Za-z0-9_.-]+#\d+(?:\.\d+)?)*)\]")
_QUOTE_RE = re.compile(r"\"([^\"\n]{1,400})\"")
# curly quotes -> straight quotes (written as escapes to keep the source ASCII)
_SMART = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


@dataclass
class GroundingResult:
    ok: bool
    citations: list[str] = field(default_factory=list)       # every cited id, in order, with repeats
    valid_citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    bad_quotes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def cited_ids(self) -> list[str]:
        return sorted(set(self.valid_citations))


def _norm(s: str) -> str:
    s = s.translate(_SMART).lower()
    s = re.sub(r"[^\w\s'%$.,:/>-]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def parse_citations(text: str) -> list[tuple[int, int, list[str]]]:
    out = []
    for m in _CITE_RE.finditer(text or ""):
        ids = [i.strip() for i in re.split(r"[,;]", m.group(1)) if i.strip()]
        out.append((m.start(), m.end(), ids))
    return out


def check_grounding(reply: str, retrieved: dict[str, str]) -> GroundingResult:
    """retrieved: chunk id -> chunk text, for the chunks retrieved for this ticket only."""
    text = (reply or "").translate(_SMART)
    cites = parse_citations(text)
    r = GroundingResult(ok=False)
    for _, _, ids in cites:
        for cid in ids:
            r.citations.append(cid)
            (r.valid_citations if cid in retrieved else r.invalid_citations).append(cid)
    if r.invalid_citations:
        r.problems.append("cites chunk ids that were not retrieved: " + ", ".join(sorted(set(r.invalid_citations))))
    for m in _QUOTE_RE.finditer(text):
        q = m.group(1).strip()
        if not q:
            continue
        r.quotes.append(q)
        if len(q.split()) > MAX_QUOTE_WORDS:
            r.bad_quotes.append(q)
            r.problems.append(f"quote longer than {MAX_QUOTE_WORDS} words")
            continue
        para_end = text.find("\n\n", m.end())
        para_end = len(text) if para_end < 0 else para_end
        following = [ids for start, _, ids in cites if m.end() <= start < para_end]
        if not following:
            r.bad_quotes.append(q)
            r.problems.append(f"quote has no citation after it: \"{q[:60]}\"")
            continue
        nq = _norm(q)
        if not any(nq and nq in _norm(retrieved.get(cid, "")) for cid in following[0]):
            r.bad_quotes.append(q)
            r.problems.append(f"quote not found word for word in the cited chunk: \"{q[:60]}\"")
    if not r.valid_citations:
        r.problems.append("no valid citations")
    r.ok = not r.problems
    return r


def strip_citations(text: str) -> str:
    return re.sub(r"\s*" + _CITE_RE.pattern, "", text or "")
