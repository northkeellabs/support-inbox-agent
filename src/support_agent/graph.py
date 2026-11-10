"""The LangGraph workflow.

validate -> lookup -> classify -> retrieve -> draft -> ground -> route -> plan -> approval (interrupt) -> execute -> report

The LLM is used in two nodes (classify, draft) and has no tools. Grounding, escalation,
the plan and its validation are all code. A human approves every plan before anything
is written, and the default is a dry run.
"""
from __future__ import annotations

import datetime as dt
import functools
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from . import prompts
from .audit import AuditLog
from .crm import Crm, CrmError
from .grounding import check_grounding
from .kb import Retriever
from .llm import StructuredOutputError, structured_call
from .schema import NOTE_MAX, TASK_PREFIX, ActionPlan, AddNote, Classification, CreateContact, CreateTask, Draft, Ticket
from .security import (looks_like_injection, mentions_legal_threat, mentions_refund_or_dispute, promises_money, sha256,
                       strip_urls, strip_urls_not_in)

MAX_EDIT_ATTEMPTS = 3
MAX_HUMAN_DRAFT = 3000
LEAK_SHINGLE_WORDS = 8


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class SupportState(TypedDict, total=False):
    run_id: str
    raw_ticket: dict
    live: bool
    ticket: dict
    status: str  # running | invalid | pending_approval | no_action | rejected | dry_run | executed | partial | failed
    reason: str
    contact_id: str | None
    lookup_note: str
    classification: dict | None
    injection_signals: list[str]
    retrieval: dict
    pre_reasons: list[str]
    draft: dict | None          # what the model wrote (after URL stripping), with check results
    offered_draft: str | None   # the draft a human may send; None when escalated
    escalate: bool
    escalation_reasons: list[str]
    plan: dict
    decision: str
    draft_edited: bool
    results: list[dict]
    timings: Annotated[dict, _merge]


@dataclass
class Deps:
    model: BaseChatModel
    retriever: Retriever
    crm: Crm
    audit: AuditLog
    min_retrieval_score: float
    provider: str = "ollama"
    today: Callable[[], dt.date] = field(default=dt.date.today)


def _timed(name: str, deps: Deps):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state: SupportState) -> dict:
            t0 = time.perf_counter()
            out = await fn(state) or {}
            secs = round(time.perf_counter() - t0, 3)
            deps.audit.write(state.get("run_id", "?"), "node", node=name, seconds=secs,
                             status=out.get("status", state.get("status")))
            return {**out, "timings": {name: secs}}
        return wrapper
    return deco


def echoes(text: str, reference: str, n: int = LEAK_SHINGLE_WORDS) -> bool:
    """True if `text` repeats any run of n consecutive words from `reference` (system prompt leak check)."""
    def words(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", s.lower())
    ref = words(reference)
    grams = {" ".join(ref[i:i + n]) for i in range(len(ref) - n + 1)}
    w = words(text)
    return any(" ".join(w[i:i + n]) in grams for i in range(len(w) - n + 1))


# ------------------------------------------------------------------ escalation rules

def pre_draft_reasons(cls: Classification | None, ticket: Ticket, top_score: float, min_score: float) -> list[str]:
    """Rules that escalate before any draft is written (so no draft is ever produced for them)."""
    text = f"{ticket.subject}\n{ticket.body}"
    reasons: list[str] = []
    if cls is None:
        reasons.append("classification failed (model returned invalid output twice)")
        return reasons
    if cls.category == "account_security":
        reasons.append("account security ticket")
    if cls.requests_other_customer_data:
        reasons.append("asks for another customer's data")
    if cls.refund_or_dispute or mentions_refund_or_dispute(text):
        reasons.append("refund request or money dispute")
    if cls.legal_threat or mentions_legal_threat(text):
        reasons.append("legal threat")
    if cls.urgency == "high" and cls.sentiment == "negative":
        reasons.append("high urgency with negative sentiment")
    if top_score < min_score:
        reasons.append(f"low retrieval score ({top_score:.3f} < {min_score:.3f})")
    return reasons


def build_plan(ticket: Ticket, cls: Classification | None, contact_id: str | None, escalate: bool, reasons: list[str],
               draft_text: str | None, sources: list[str], today: dt.date, draft_by_human: bool = False) -> ActionPlan:
    if cls is not None and cls.category == "spam" and not escalate:
        return ActionPlan(actions=[])
    cat = f"{cls.category}, urgency {cls.urgency}, sentiment {cls.sentiment}" if cls else "unknown (classification failed)"
    summary = strip_urls(cls.summary) if cls else "(none)"
    subject = strip_urls(ticket.subject)[:200]
    lines = [f"Support ticket {ticket.id} received {ticket.received_at.isoformat()} (automated triage by support-inbox-agent, logged after human approval).",
             f"Subject: {subject}", f"Category: {cat}", f"Summary: {summary}"]
    if escalate:
        lines.append("Decision: ESCALATED to a human. Reasons: " + "; ".join(reasons) + ". No reply has been sent.")
    else:
        lines.append("Decision: draft reply prepared for a human to review and send. Nothing was sent by the agent.")
    if draft_text:
        who = "Draft reply (edited by a human reviewer)" if draft_by_human else "Draft reply"
        lines.append(f"{who}:\n{draft_text}")
    if sources:
        lines.append(("Cited sources: " if not escalate else "Knowledge-base sources consulted: ") + ", ".join(sources))
    note = "\n".join(lines)
    if len(note) > NOTE_MAX:
        note = note[:NOTE_MAX - 15] + "\n[truncated]"
    actions: list = []
    if not contact_id:
        actions.append(CreateContact(action="create_contact", name=ticket.from_name, email=ticket.from_email,
                                     background_info="Support ticket sender (record created by support-inbox-agent after human approval)."))
    actions.append(AddNote(action="add_note", contact_id=contact_id, note=note))
    if escalate:
        actions.append(CreateTask(action="create_task", contact_id=contact_id, name=(TASK_PREFIX + subject)[:200],
                                  due_date=today,
                                  description=(f"Ticket {ticket.id} from {ticket.from_name}. Reasons: " + "; ".join(reasons)
                                               + ". Reply to the customer yourself; the agent sent nothing.")[:1000]))
    return ActionPlan(actions=actions)


def check_plan_targets(p: ActionPlan, contact_id: str | None, sender_email: str) -> None:
    """A plan may only touch the sender's own record: their existing contact, or one new contact with their email."""
    allowed = {contact_id} if contact_id else set()
    if p.contact_ids() - allowed:
        raise ValueError("plan targets a contact other than the ticket sender's own record")
    created = p.created_emails()
    if created and (contact_id or created != {sender_email.lower()}):
        raise ValueError("plan may only create one contact, for the ticket sender, and only if none exists")


# ------------------------------------------------------------------ graph

def build_graph(deps: Deps, checkpointer=None):
    audit = deps.audit

    @_timed("validate", deps)
    async def validate(state: SupportState) -> dict:
        try:
            t = Ticket.model_validate(state["raw_ticket"])
        except ValidationError as exc:
            errs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())[:500]
            audit.write(state["run_id"], "invalid_input", errors=errs)
            return {"status": "invalid", "reason": errs}
        audit.write(state["run_id"], "input", ticket_id=t.id, email_hash=sha256(t.from_email.lower()),
                    name_hash=sha256(t.from_name), subject_hash=sha256(t.subject), body_hash=sha256(t.body),
                    live=state.get("live", False))
        return {"ticket": t.model_dump(mode="json"), "status": "running"}

    @_timed("lookup", deps)
    async def lookup(state: SupportState) -> dict:
        t = Ticket.model_validate(state["ticket"])
        contact, note = None, "no existing contact with this email; the plan creates one"
        try:
            for r in await deps.crm.search(t.from_email):
                if (r.get("email") or "").lower() == t.from_email.lower() and not r.get("is_company"):
                    contact = str(r.get("contact_id"))
                    break
            audit.write(state["run_id"], "tool_call", tool="search_contacts", mode="read-only", found=bool(contact))
        except Exception as exc:  # a lookup failure must not crash triage
            note = f"CRM lookup failed ({type(exc).__name__}); check for an existing contact before approving"
            audit.write(state["run_id"], "tool_error", tool="search_contacts", error=type(exc).__name__)
        if contact:
            note = "sender is an existing contact; the note goes on that record"
        return {"contact_id": contact, "lookup_note": note}

    @_timed("classify", deps)
    async def classify(state: SupportState) -> dict:
        t = Ticket.model_validate(state["ticket"])
        signals = looks_like_injection(f"{t.subject}\n{t.body}")
        try:
            c, attempts = await structured_call(deps.model, prompts.classify_system(), prompts.classify_user(t),
                                                Classification, deps.provider)
        except StructuredOutputError as exc:
            audit.write(state["run_id"], "llm_invalid_output", node="classify", attempts=exc.attempts, error=str(exc)[:300])
            return {"classification": None, "injection_signals": signals}
        audit.write(state["run_id"], "decision", node="classify", category=c.category, urgency=c.urgency,
                    sentiment=c.sentiment, refund_or_dispute=c.refund_or_dispute, legal_threat=c.legal_threat,
                    other_customer=c.requests_other_customer_data, attempts=attempts, injection_signals=len(signals))
        return {"classification": c.model_dump(), "injection_signals": signals}

    @_timed("retrieve", deps)
    async def retrieve(state: SupportState) -> dict:
        t = Ticket.model_validate(state["ticket"])
        r = deps.retriever.retrieve(f"{t.subject}\n{t.body}"[:4000])
        hits = [{"id": h.chunk.id, "source": h.chunk.source, "heading": h.chunk.heading, "text": h.chunk.text,
                 "rrf": h.rrf, "vector_score": h.vector_score, "bm25": h.bm25} for h in r.hits]
        audit.write(state["run_id"], "retrieval", chunk_ids=r.ids, sources=r.sources,
                    top_vector_score=round(r.top_vector_score, 4))
        return {"retrieval": {"hits": hits, "top_vector_score": r.top_vector_score}}

    @_timed("draft", deps)
    async def draft(state: SupportState) -> dict:
        t = Ticket.model_validate(state["ticket"])
        cls = Classification.model_validate(state["classification"]) if state.get("classification") else None
        top = state["retrieval"]["top_vector_score"]
        reasons = pre_draft_reasons(cls, t, top, deps.min_retrieval_score)
        if reasons:  # never draft a reply for a ticket that must go to a human anyway
            audit.write(state["run_id"], "decision", node="draft", skipped=True, reasons=reasons)
            return {"pre_reasons": reasons, "draft": None}
        hits_by_id = {h["id"]: h["text"] for h in state["retrieval"]["hits"]}
        from .kb import Chunk, Hit
        hits = [Hit(chunk=Chunk(id=h["id"], source=h["source"], heading=h["heading"], text=h["text"]), rrf=h["rrf"])
                for h in state["retrieval"]["hits"]]
        user = prompts.draft_user(t, hits)
        extra: list = []
        first_check = None
        attempts_total = 0
        d = None
        for round_ in (1, 2):
            try:
                d, attempts = await structured_call(deps.model, prompts.draft_system(), user, Draft, deps.provider, extra)
            except StructuredOutputError as exc:
                audit.write(state["run_id"], "llm_invalid_output", node="draft", attempts=exc.attempts, error=str(exc)[:300])
                return {"pre_reasons": [], "draft": {"error": "model returned invalid JSON twice while drafting",
                                                     "can_answer": False, "reply": ""}}
            attempts_total += attempts
            if not d.can_answer:
                break
            g = check_grounding(d.reply, hits_by_id)
            if first_check is None:
                first_check = {"citations": len(g.citations), "valid": len(g.valid_citations), "ok": g.ok,
                               "problems": g.problems}
            if g.ok or round_ == 2:
                break
            # one repair round: show the model exactly what failed the check
            extra = [AIMessage(d.model_dump_json()), HumanMessage(prompts.grounding_retry(g.problems, list(hits_by_id)))]
            audit.write(state["run_id"], "grounding_retry", problems=g.problems)
        audit.write(state["run_id"], "decision", node="draft", can_answer=d.can_answer, attempts=attempts_total,
                    first_check=first_check)
        return {"pre_reasons": [], "draft": {"can_answer": d.can_answer, "reply": d.reply, "first_check": first_check,
                                             "model_reply": d.reply}}

    @_timed("ground", deps)
    async def ground(state: SupportState) -> dict:
        d = state.get("draft")
        if not d or not d.get("can_answer") or not d.get("reply"):
            return {}
        hits_by_id = {h["id"]: h["text"] for h in state["retrieval"]["hits"]}
        reply, removed = strip_urls_not_in(d["reply"], deps.retriever.all_text)
        g = check_grounding(reply, hits_by_id)
        promises = promises_money(reply)
        leak = echoes(reply, prompts.all_system_text())
        audit.write(state["run_id"], "grounding", ok=g.ok, citations=len(g.citations), valid=len(g.valid_citations),
                    cited_ids=g.cited_ids, quotes=len(g.quotes), bad_quotes=len(g.bad_quotes), removed_urls=len(removed),
                    money_promises=len(promises), system_prompt_echo=leak)
        return {"draft": {**d, "reply": reply, "removed_urls": removed, "grounding": {
            "ok": g.ok, "citations": g.citations, "valid": g.valid_citations, "invalid": g.invalid_citations,
            "cited_ids": g.cited_ids, "quotes": g.quotes, "bad_quotes": g.bad_quotes, "problems": g.problems},
            "money_promises": promises, "system_prompt_echo": leak}}

    @_timed("route", deps)
    async def route(state: SupportState) -> dict:
        reasons = list(state.get("pre_reasons") or [])
        d = state.get("draft")
        if not reasons:
            if not d or d.get("error"):
                reasons.append((d or {}).get("error") or "no draft")
            elif not d.get("can_answer") or not d.get("reply"):
                reasons.append("no grounded answer in the knowledge base")
            else:
                g = d["grounding"]
                if not g["valid"]:
                    reasons.append("no grounded answer (draft had zero valid citations)")
                elif not g["ok"]:
                    reasons.append("grounding check failed: " + "; ".join(g["problems"])[:300])
                if d.get("money_promises"):
                    reasons.append("draft promised a refund, credit or discount")
                if d.get("system_prompt_echo"):
                    reasons.append("draft repeated the system instructions")
        escalate = bool(reasons)
        offered = None if escalate else d["reply"]
        audit.write(state["run_id"], "decision", node="route", escalate=escalate, reasons=reasons)
        return {"escalate": escalate, "escalation_reasons": reasons, "offered_draft": offered}

    def _sources(state: SupportState) -> list[str]:
        hits = state["retrieval"]["hits"] if state.get("retrieval") else []
        src = {h["id"]: h["source"] for h in hits}
        if state.get("offered_draft"):
            ids = (state.get("draft") or {}).get("grounding", {}).get("cited_ids", [])
        else:
            ids = [h["id"] for h in hits]
        by_source: dict[str, list[str]] = {}
        for cid in ids:
            by_source.setdefault(src.get(cid, "?"), []).append(cid)
        return [f"{s} ({', '.join(v)})" for s, v in sorted(by_source.items())]

    @_timed("plan", deps)
    async def plan(state: SupportState) -> dict:
        t = Ticket.model_validate(state["ticket"])
        cls = Classification.model_validate(state["classification"]) if state.get("classification") else None
        p = build_plan(t, cls, state.get("contact_id"), state.get("escalate", False), state.get("escalation_reasons", []),
                       state.get("offered_draft"), _sources(state) if state.get("retrieval") else [], deps.today())
        check_plan_targets(p, state.get("contact_id"), t.from_email)
        audit.write(state["run_id"], "plan", actions=[a.action for a in p.actions])
        return {"plan": p.model_dump(mode="json"), "status": "pending_approval" if p.actions else "no_action"}

    async def approval(state: SupportState) -> dict:
        # No @_timed here: the wait for a human is not processing time.
        prompt = {"run_id": state["run_id"], "ticket": state["ticket"], "classification": state.get("classification"),
                  "escalate": state.get("escalate"), "escalation_reasons": state.get("escalation_reasons"),
                  "draft": state.get("offered_draft"), "plan": state["plan"], "lookup_note": state.get("lookup_note"),
                  "live": state.get("live", False)}
        t = Ticket.model_validate(state["ticket"])
        error = None
        for _ in range(MAX_EDIT_ATTEMPTS):
            resp = interrupt({**prompt, "error": error})
            decision = (resp or {}).get("decision") if isinstance(resp, dict) else resp
            if decision == "approve":
                audit.write(state["run_id"], "approval", decision="approve")
                return {"decision": "approve"}
            if decision == "reject":
                audit.write(state["run_id"], "approval", decision="reject")
                return {"decision": "reject", "status": "rejected"}
            if decision == "edit":
                try:
                    out: dict[str, Any] = {"decision": "edit"}
                    if isinstance(resp.get("plan"), dict):
                        p = ActionPlan.model_validate(resp["plan"])
                    elif isinstance(resp.get("draft"), str) and resp["draft"].strip():
                        text = resp["draft"].strip()
                        if len(text) > MAX_HUMAN_DRAFT:
                            raise ValueError(f"edited draft longer than {MAX_HUMAN_DRAFT} characters")
                        cls = Classification.model_validate(state["classification"]) if state.get("classification") else None
                        p = build_plan(t, cls, state.get("contact_id"), state.get("escalate", False),
                                       state.get("escalation_reasons", []), text, _sources(state), deps.today(),
                                       draft_by_human=True)
                        out.update({"offered_draft": text, "draft_edited": True})
                    else:
                        raise ValueError("edit needs a 'draft' string or a 'plan' object")
                    check_plan_targets(p, state.get("contact_id"), t.from_email)
                except (ValidationError, ValueError) as exc:
                    error = f"edit rejected: {str(exc)[:300]}"
                    audit.write(state["run_id"], "approval", decision="edit_invalid", error=error)
                    continue
                out["plan"] = p.model_dump(mode="json")
                audit.write(state["run_id"], "approval", decision="edit", actions=[a.action for a in p.actions])
                return out
            error = f"unknown decision {decision!r}; use approve, edit or reject"
        audit.write(state["run_id"], "approval", decision="reject", reason="too many invalid responses")
        return {"decision": "reject", "status": "rejected", "reason": "too many invalid approval responses"}

    @_timed("execute", deps)
    async def execute(state: SupportState) -> dict:
        p = ActionPlan.model_validate(state["plan"])  # re-validate right before acting
        t = Ticket.model_validate(state["ticket"])
        check_plan_targets(p, state.get("contact_id"), t.from_email)
        if not state.get("live"):
            results = [{"action": a.action, "dry_run": True} for a in p.actions]
            audit.write(state["run_id"], "execute", mode="dry-run", write_calls=0, actions=[a.action for a in p.actions])
            return {"results": results, "status": "dry_run"}
        results: list[dict] = []
        contact_id = state.get("contact_id")
        try:
            async with deps.crm.writer() as w:
                for a in p.actions:
                    if isinstance(a, CreateContact):
                        args = a.model_dump(exclude={"action"}, exclude_none=True)
                        r = await w.call("create_contact", args)
                        contact_id = str(r.get("contact_id") or "") or None
                        if not contact_id:
                            raise CrmError("create_contact returned no contact id")
                    elif isinstance(a, AddNote):
                        r = await w.call("add_note", {"contact_id": a.contact_id or contact_id, "note": a.note})
                    else:
                        args = {"name": a.name, "due_date": a.due_date.isoformat(), "contact_id": a.contact_id or contact_id}
                        if a.description:
                            args["description"] = a.description
                        r = await w.call("create_task", args)
                    results.append({"action": a.action, "ok": True, **{k: v for k, v in r.items() if k.endswith("_id")}})
                    audit.write(state["run_id"], "tool_call", tool=a.action, mode="write", ok=True)
        except Exception as exc:  # do not retry non-idempotent writes
            msg = str(exc)[:300] if isinstance(exc, CrmError) else type(exc).__name__
            audit.write(state["run_id"], "tool_error", node="execute", error=msg, completed=len(results))
            return {"results": results + [{"error": msg}], "status": "partial" if results else "failed", "reason": msg}
        return {"results": results, "status": "executed"}

    @_timed("report", deps)
    async def report(state: SupportState) -> dict:
        audit.write(state["run_id"], "report", status=state.get("status"),
                    category=(state.get("classification") or {}).get("category"), escalate=state.get("escalate"),
                    timings=state.get("timings"))
        return {}

    def after_validate(s: SupportState) -> str:
        return "report" if s.get("status") == "invalid" else "lookup"

    def after_classify(s: SupportState) -> str:
        return "plan" if (s.get("classification") or {}).get("category") == "spam" else "retrieve"

    def after_plan(s: SupportState) -> str:
        return "approval" if (s.get("plan") or {}).get("actions") else "report"

    def after_approval(s: SupportState) -> str:
        return "execute" if s.get("decision") in ("approve", "edit") else "report"

    g = StateGraph(SupportState)
    for name, fn in [("validate", validate), ("lookup", lookup), ("classify", classify), ("retrieve", retrieve),
                     ("draft", draft), ("ground", ground), ("route", route), ("plan", plan), ("approval", approval),
                     ("execute", execute), ("report", report)]:
        g.add_node(name, fn)
    g.add_edge(START, "validate")
    g.add_conditional_edges("validate", after_validate, ["lookup", "report"])
    g.add_edge("lookup", "classify")
    g.add_conditional_edges("classify", after_classify, ["retrieve", "plan"])
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", "ground")
    g.add_edge("ground", "route")
    g.add_edge("route", "plan")
    g.add_conditional_edges("plan", after_plan, ["approval", "report"])
    g.add_conditional_edges("approval", after_approval, ["execute", "report"])
    g.add_edge("execute", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)
