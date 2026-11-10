"""Shared runner for the CLI and the webhook: SQLite checkpointer + run index."""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .audit import AuditLog
from .config import Settings, known_secrets
from .crm import Crm, McpCrm
from .graph import Deps, build_graph
from .kb import Embedder, OllamaEmbedder, Retriever
from .llm import make_model


def new_run_id(ticket_id: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (ticket_id or "ticket").lower()).strip("-")[:24] or "ticket"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


class RunIndex:
    """Tiny table of runs so pending approvals can be listed after a restart."""

    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, ticket TEXT, status TEXT, "
                      "created TEXT DEFAULT CURRENT_TIMESTAMP)")

    def set(self, run_id: str, ticket: str, status: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO runs (run_id, ticket, status) VALUES (?,?,?) "
                      "ON CONFLICT(run_id) DO UPDATE SET status=excluded.status", (run_id, ticket, status))

    def pending(self) -> list[tuple[str, str, str]]:
        with sqlite3.connect(self.path) as c:
            return c.execute("SELECT run_id, ticket, created FROM runs WHERE status='pending_approval' "
                             "ORDER BY created").fetchall()


class Runner:
    def __init__(self, graph, index: RunIndex | None):
        self.graph, self.index = graph, index

    async def start(self, raw_ticket: dict, live: bool = False, run_id: str | None = None) -> dict:
        run_id = run_id or new_run_id(str(raw_ticket.get("id", "")))
        state = await self.graph.ainvoke({"run_id": run_id, "raw_ticket": raw_ticket, "live": live, "timings": {}},
                                         {"configurable": {"thread_id": run_id}})
        return await self._result(run_id, state)

    async def resume(self, run_id: str, response: dict) -> dict:
        state = await self.graph.ainvoke(Command(resume=response), {"configurable": {"thread_id": run_id}})
        return await self._result(run_id, state)

    async def pending_payload(self, run_id: str) -> dict | None:
        snap = await self.graph.aget_state({"configurable": {"thread_id": run_id}})
        if snap.interrupts:
            return snap.interrupts[0].value
        return None

    async def _result(self, run_id: str, state: dict) -> dict:
        interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
        status = "pending_approval" if interrupts else state.get("status", "unknown")
        if self.index:
            self.index.set(run_id, str((state.get("ticket") or state.get("raw_ticket") or {}).get("id", "")), status)
        return {"run_id": run_id, "status": status, "state": state,
                "approval": interrupts[0].value if interrupts else None}


def make_embedder(settings: Settings) -> Embedder:
    return OllamaEmbedder(settings.embed_model, settings.ollama_base_url)


@asynccontextmanager
async def open_runner(settings: Settings, *, crm: Crm | None = None, retriever: Retriever | None = None,
                      embedder: Embedder | None = None, model=None) -> AsyncIterator[Runner]:
    settings.ensure_dirs()
    retriever = retriever or Retriever(settings.kb_index, embedder or make_embedder(settings))
    deps = Deps(model=model or make_model(settings), retriever=retriever, crm=crm or McpCrm(settings),
                audit=AuditLog(settings.data_dir / "audit", known_secrets()),
                min_retrieval_score=settings.min_retrieval_score, provider=settings.model_provider)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db)) as saver:
        yield Runner(build_graph(deps, saver), RunIndex(settings.data_dir / "runs.sqlite"))


def summarize(result: dict[str, Any]) -> str:
    """Human-readable summary of a run (used by CLI, saved outputs)."""
    st = result.get("state") or {}
    ap = result.get("approval") or {}
    lines = [f"run_id: {result['run_id']}", f"status: {result['status']}"]
    t = st.get("ticket") or ap.get("ticket")
    if t:
        lines.append(f"ticket: {t['id']} from {t['from_name']} <{t['from_email']}>: {t['subject']}")
    c = st.get("classification") or ap.get("classification")
    if c:
        lines.append(f"category: {c['category']}  urgency: {c['urgency']}  sentiment: {c['sentiment']}")
        lines.append(f"  summary: {c['summary']}")
    if st.get("injection_signals"):
        lines.append("injection phrases detected (flag only): " + ", ".join(st["injection_signals"]))
    if st.get("reason"):
        lines.append(f"reason: {st['reason']}")
    if st.get("lookup_note") or ap.get("lookup_note"):
        lines.append(f"crm: {st.get('lookup_note') or ap.get('lookup_note')}")
    r = st.get("retrieval")
    if r:
        lines.append(f"retrieved (top vector similarity {r['top_vector_score']:.3f}):")
        lines += [f"  - {h['id']}  ({h['source']}; rrf={h['rrf']}, vec={h['vector_score']}, bm25={h['bm25']})" for h in r["hits"]]
    if "escalate" in st or "escalate" in ap:
        esc = st.get("escalate", ap.get("escalate"))
        reasons = st.get("escalation_reasons") or ap.get("escalation_reasons") or []
        lines.append("decision: ESCALATE (" + "; ".join(reasons) + ")" if esc else "decision: draft for approval")
    d = (st.get("draft") or {})
    if d.get("grounding"):
        g = d["grounding"]
        lines.append(f"grounding: {'ok' if g['ok'] else 'FAILED'}; citations {len(g['valid'])}/{len(g['citations'])} valid; "
                     f"quotes {len(g['quotes'])} ({len(g['bad_quotes'])} bad)" + (f"; problems: {'; '.join(g['problems'])}" if g["problems"] else ""))
    offered = st.get("offered_draft") if "offered_draft" in st else ap.get("draft")
    if offered:
        lines += ["draft reply (NOT sent):"] + ["  " + l for l in offered.splitlines()]
    plan = st.get("plan") or ap.get("plan")
    if plan:
        lines.append("action plan:")
        for a in plan.get("actions", []):
            lines.append("  - " + ", ".join(f"{k}={v}" for k, v in a.items() if k != "note"))
            if "note" in a:
                lines += ["      | " + l for l in a["note"].splitlines()]
    if st.get("results"):
        lines.append("execution:")
        lines += [f"  - {r}" for r in st["results"]]
    if st.get("timings"):
        lines.append("timings (s): " + ", ".join(f"{k}={v}" for k, v in st["timings"].items()))
    return "\n".join(lines)
