"""Knowledge base: heading-based chunking, embeddings, sqlite-vec store, BM25, RRF.

Retrieval reads only the knowledge-base index built from Markdown files. Tickets are
never indexed, so one customer's text can never be retrieved for another.
"""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

import sqlite_vec

MAX_WORDS = 180      # longer sections are split into overlapping windows
OVERLAP_WORDS = 40
VECTOR_K = 10
BM25_K = 10
RRF_K = 60
TOP_N = 5

_HTML_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_HIDDEN_HTML_RE = re.compile(r"(?is)<(\w+)[^>]*(?:display\s*:\s*none|visibility\s*:\s*hidden|\bhidden\b|aria-hidden=\"true\")[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]{1,200}>")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by can do does for from how i if in is it its me my of on or our so that the this to we what when where which who why will with you your".split())


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """bge-m3 (or any Ollama embedding model) through langchain-ollama."""

    def __init__(self, model: str, base_url: str):
        from langchain_ollama import OllamaEmbeddings
        self.name = model
        self._e = OllamaEmbeddings(model=model, base_url=base_url)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._e.embed_documents(texts)


@dataclass(frozen=True)
class Chunk:
    id: str        # "<article-slug>#<section>" or "<slug>#<section>.<window>"
    source: str    # "kb/<file>.md"
    heading: str   # "Article title > Section"
    text: str      # what the model sees and what quotes are checked against


@dataclass
class Hit:
    chunk: Chunk
    rrf: float
    vector_score: float | None = None  # cosine similarity, None if not in vector top-k
    bm25: float | None = None


@dataclass
class Retrieval:
    hits: list[Hit]
    top_vector_score: float  # best cosine similarity over the vector candidates
    candidates: dict = field(default_factory=dict)

    @property
    def ids(self) -> list[str]:
        return [h.chunk.id for h in self.hits]

    @property
    def sources(self) -> list[str]:
        return sorted({h.chunk.source for h in self.hits})


# ------------------------------------------------------------------ chunking

def clean_markdown(text: str) -> str:
    """Drop HTML comments and hidden HTML elements, then any remaining tags. Visible text is kept."""
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HIDDEN_HTML_RE.sub("", text)
    return _TAG_RE.sub("", text)


def _windows(words: list[str]) -> list[list[str]]:
    if len(words) <= MAX_WORDS:
        return [words]
    out, step = [], MAX_WORDS - OVERLAP_WORDS
    for start in range(0, len(words), step):
        out.append(words[start:start + MAX_WORDS])
        if start + MAX_WORDS >= len(words):
            break
    return out


def chunk_markdown(text: str, source: str) -> list[Chunk]:
    """Split by headings. Each chunk starts with its heading path; long sections become overlapping windows."""
    slug = Path(source).stem
    lines = clean_markdown(text).splitlines()
    title, sections, cur_head, cur = None, [], "Overview", []
    for line in lines:
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m and m.group(1) == "#" and title is None:
            title = m.group(2).strip()
        elif line.startswith(">") and not sections:
            continue  # the article's label blockquote before the first section
        elif m:
            sections.append((cur_head, cur))
            cur_head, cur = m.group(2).strip(), []
        else:
            cur.append(line)
    sections.append((cur_head, cur))
    title = title or slug
    chunks: list[Chunk] = []
    si = 0
    for head, body in sections:
        paras = [re.sub(r"\s+", " ", p).strip() for p in "\n".join(body).split("\n\n")]
        body_text = " ".join(p for p in paras if p)
        if len(body_text.split()) < 12:  # skip empty sections and the one-line intro label
            continue
        si += 1
        wins = _windows(body_text.split(" "))
        for wi, w in enumerate(wins, start=1):
            cid = f"{slug}#{si}" if len(wins) == 1 else f"{slug}#{si}.{wi}"
            heading = f"{title} > {head}"
            chunks.append(Chunk(id=cid, source=source, heading=heading, text=f"{heading}\n{' '.join(w)}"))
    return chunks


def load_kb(dirs: Iterable[Path]) -> list[Chunk]:
    """All *.md files in the given folders, sorted by name, chunked. Source paths are 'kb/<name>'."""
    files: dict[str, Path] = {}
    for d in dirs:
        for f in sorted(Path(d).glob("*.md")):
            if f.name.lower() == "readme.md":
                continue
            files[f.name] = f  # later folders may add articles (eval fixture); names must be unique
    chunks: list[Chunk] = []
    for name in sorted(files):
        chunks += chunk_markdown(files[name].read_text(encoding="utf-8"), f"kb/{name}")
    return chunks


# ------------------------------------------------------------------ BM25 + RRF

def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(c.values()) for c in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for c, ln in zip(self.docs, self.lens):
            s = 0.0
            for t in q:
                tf = c.get(t, 0)
                if tf:
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1)))
            out.append(s)
        return out


def rrf_merge(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion. Ties broken by id so the order is deterministic."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))


# ------------------------------------------------------------------ store

def _connect(path: Path | str) -> sqlite3.Connection:
    # check_same_thread=False: the web server may call from another thread; Retriever serialises access with a lock.
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    return c


def kb_fingerprint(chunks: list[Chunk], embed_model: str) -> str:
    h = hashlib.sha256(embed_model.encode())
    for ch in chunks:
        h.update(f"\x00{ch.id}\x00{ch.source}\x00{ch.text}".encode())
    return h.hexdigest()[:16]


def build_index(chunks: list[Chunk], embedder: Embedder, path: Path, batch: int = 16) -> dict:
    """Rebuild the index from scratch (deterministic: same files + same model -> same rows)."""
    if not chunks:
        raise ValueError("knowledge base is empty: no Markdown files found")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    vecs: list[list[float]] = []
    for i in range(0, len(chunks), batch):
        vecs += embedder.embed([c.text for c in chunks[i:i + batch]])
    dim = len(vecs[0])
    c = _connect(tmp)
    try:
        c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, source TEXT, heading TEXT, text TEXT)")
        c.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}] distance_metric=cosine)")
        for i, (ch, v) in enumerate(zip(chunks, vecs), start=1):
            c.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (i, ch.id, ch.source, ch.heading, ch.text))
            c.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)", (i, sqlite_vec.serialize_float32(v)))
        fp = kb_fingerprint(chunks, embedder.name)
        c.executemany("INSERT INTO meta VALUES (?,?)", [("embed_model", embedder.name), ("dim", str(dim)),
                                                       ("fingerprint", fp), ("chunks", str(len(chunks)))])
        c.commit()
    finally:
        c.close()
    if path.exists():
        path.unlink()
    tmp.rename(path)
    return {"chunks": len(chunks), "dim": dim, "fingerprint": fp, "articles": len({ch.source for ch in chunks})}


class Retriever:
    """Hybrid retrieval over one index file: vector top-k + BM25 top-k, merged by RRF, top 5."""

    def __init__(self, path: Path, embedder: Embedder):
        if not Path(path).exists():
            raise FileNotFoundError(f"no knowledge-base index at {path}; run `support kb index` first")
        self.path, self.embedder = Path(path), embedder
        self._lock = threading.Lock()
        self._c = _connect(self.path)
        self.meta = dict(self._c.execute("SELECT key, value FROM meta").fetchall())
        if self.meta.get("embed_model") != embedder.name:
            raise ValueError(f"index was built with {self.meta.get('embed_model')!r}, not {embedder.name!r}; re-run `support kb index`")
        rows = self._c.execute("SELECT rowid, id, source, heading, text FROM chunks ORDER BY rowid").fetchall()
        self.rowids = [r[0] for r in rows]
        self.chunks = [Chunk(id=r[1], source=r[2], heading=r[3], text=r[4]) for r in rows]
        self.by_id = {c.id: c for c in self.chunks}
        self._by_rowid = dict(zip(self.rowids, self.chunks))
        self.bm25 = BM25([c.text for c in self.chunks])
        self.all_text = "\n".join(c.text for c in self.chunks)

    def close(self) -> None:
        self._c.close()

    def retrieve(self, query: str, top_n: int = TOP_N) -> Retrieval:
        qv = self.embedder.embed([query])[0]
        with self._lock:
            rows = self._c.execute(
                "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(qv), VECTOR_K)).fetchall()
        rows = sorted(rows, key=lambda r: (round(r[1], 6), r[0]))  # deterministic tie-break by row
        vec_rank = [self._by_rowid[r].id for r, _ in rows]
        vec_score = {self._by_rowid[r].id: round(1.0 - d, 6) for r, d in rows}
        bm = self.bm25.scores(query)
        order = sorted(range(len(bm)), key=lambda i: (-bm[i], self.chunks[i].id))
        bm_rank = [self.chunks[i].id for i in order[:BM25_K] if bm[i] > 0]
        bm_score = {self.chunks[i].id: round(bm[i], 6) for i in order[:BM25_K] if bm[i] > 0}
        merged = rrf_merge([vec_rank, bm_rank])[:top_n]
        hits = [Hit(chunk=self.by_id[cid], rrf=round(s, 6), vector_score=vec_score.get(cid), bm25=bm_score.get(cid))
                for cid, s in merged]
        top = max(vec_score.values()) if vec_score else 0.0
        return Retrieval(hits=hits, top_vector_score=top, candidates={"vector": vec_rank, "bm25": bm_rank})
