import pytest
from langgraph.types import Command

from conftest import EXISTING, GOOD_REPLY, TICKET, TODAY, FakeCrm, cfg, cls_json, draft_json, start_state


def kinds(s):
    return [a["action"] for a in s["plan"]["actions"]]


# ------------------------------------------------------------- happy path + routing per category

@pytest.mark.parametrize("category", ["how_to", "billing", "bug", "feature_request"])
async def test_answerable_categories_get_a_grounded_draft(make_graph, category):
    g, crm, _ = make_graph([cls_json(category=category), draft_json(GOOD_REPLY)], crm=FakeCrm(existing=EXISTING))
    s = await g.ainvoke(start_state(), cfg())
    assert s["__interrupt__"]
    assert s["escalate"] is False and s["escalation_reasons"] == []
    assert s["offered_draft"] and "[webhooks#3]" in s["offered_draft"]
    assert kinds(s) == ["add_note"]  # known sender, no escalation: one note, no task
    note = s["plan"]["actions"][0]["note"]
    assert f"Category: {category}" in note and "Draft reply:" in note and "kb/webhooks.md (webhooks#3)" in note
    assert crm.write_calls == []


async def test_spam_gets_no_retrieval_no_draft_no_plan(make_graph):
    g, crm, _ = make_graph([cls_json(category="spam")])
    s = await g.ainvoke(start_state(), cfg())
    assert "__interrupt__" not in s and s["status"] == "no_action"
    assert "retrieval" not in s and s["plan"]["actions"] == []
    assert crm.writer_opened == 0


async def test_invalid_ticket_goes_straight_to_report(make_graph):
    g, crm, _ = make_graph([])
    s = await g.ainvoke(start_state(ticket={**TICKET, "from_email": "nope"}), cfg())
    assert s["status"] == "invalid" and crm.search_calls == []


# ------------------------------------------------------------- escalation rules

ESCALATIONS = [
    ("account_security", cls_json(category="account_security"), TICKET["body"], "account security ticket"),
    ("refund flag", cls_json(category="billing", refund_or_dispute=True), TICKET["body"], "refund request or money dispute"),
    ("refund keyword", cls_json(category="billing"), "I was charged twice, I want my money back.", "refund request or money dispute"),
    ("legal flag", cls_json(legal_threat=True), TICKET["body"], "legal threat"),
    ("legal keyword", cls_json(), "Fix this or my lawyer will be in touch.", "legal threat"),
    ("high+negative", cls_json(category="bug", urgency="high", sentiment="negative"), TICKET["body"], "high urgency with negative sentiment"),
    ("other customer", cls_json(requests_other_customer_data=True), TICKET["body"], "asks for another customer's data"),
]


@pytest.mark.parametrize("name,cls,body,reason", ESCALATIONS, ids=[e[0] for e in ESCALATIONS])
async def test_pre_draft_escalation_rules(make_graph, name, cls, body, reason):
    g, crm, audit = make_graph([cls], crm=FakeCrm(existing=EXISTING))  # no draft response: the model must not be asked
    s = await g.ainvoke(start_state(ticket={**TICKET, "body": body}), cfg())
    assert s["escalate"] is True and reason in s["escalation_reasons"]
    assert s["draft"] is None and s["offered_draft"] is None
    assert kinds(s) == ["add_note", "create_task"]
    task = s["plan"]["actions"][1]
    assert task["name"] == "Escalation: " + TICKET["subject"] and task["due_date"] == TODAY.isoformat()
    assert "ESCALATED" in s["plan"]["actions"][0]["note"]


async def test_normal_urgency_negative_sentiment_is_not_escalated(make_graph):
    g, _, _ = make_graph([cls_json(sentiment="negative"), draft_json(GOOD_REPLY)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] is False


async def test_low_retrieval_score_escalates(make_graph):
    g, _, _ = make_graph([cls_json()], min_score=0.999)
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and any(r.startswith("low retrieval score") for r in s["escalation_reasons"])


async def test_model_says_cannot_answer_escalates(make_graph):
    g, _, _ = make_graph([cls_json(), draft_json("", can_answer=False)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and "no grounded answer in the knowledge base" in s["escalation_reasons"]


async def test_zero_citations_escalates_after_one_repair(make_graph):
    uncited = "Hi Maya, just compare the header with your secret. [Your name], Ledgerline (Demo) Support"
    g, _, audit = make_graph([cls_json(), draft_json(uncited), draft_json(uncited)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and any("zero valid citations" in r for r in s["escalation_reasons"])
    assert s["offered_draft"] is None
    assert any(e["event"] == "grounding_retry" for e in audit.events)


async def test_invalid_citation_escalates(make_graph):
    bad = "Signatures use HMAC [webhooks#3]. You get a full year free [pricing-and-plans#99]."
    g, _, _ = make_graph([cls_json(), draft_json(bad), draft_json(bad)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and any("grounding check failed" in r and "not retrieved" in r for r in s["escalation_reasons"])


async def test_fabricated_quote_escalates(make_graph):
    bad = 'The article says "signatures are optional for small accounts" [webhooks#3].'
    g, _, _ = make_graph([cls_json(), draft_json(bad), draft_json(bad)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and any("word for word" in r for r in s["escalation_reasons"])


async def test_grounding_repair_round_can_succeed(make_graph):
    g, _, audit = make_graph([cls_json(), draft_json("No citations here."), draft_json(GOOD_REPLY)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] is False and s["offered_draft"]
    assert s["draft"]["first_check"]["ok"] is False


async def test_money_promise_in_draft_escalates(make_graph):
    reply = GOOD_REPLY.replace("Support", "Support. We will issue you a full refund [webhooks#3].")
    g, _, _ = make_graph([cls_json(), draft_json(reply)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and "draft promised a refund, credit or discount" in s["escalation_reasons"]


async def test_system_prompt_echo_escalates(make_graph):
    from support_agent import prompts
    leaked = " ".join(prompts.draft_system().split()[:30])
    g, _, _ = make_graph([cls_json(), draft_json(GOOD_REPLY + "\n" + leaked)])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and "draft repeated the system instructions" in s["escalation_reasons"]
    assert leaked not in s["plan"]["actions"][-2 if len(s["plan"]["actions"]) > 1 else 0]["note"]


async def test_classification_failure_escalates_with_a_note(make_graph):
    g, _, _ = make_graph(["not json", '{"category": "nonsense"}'])
    s = await g.ainvoke(start_state(), cfg())
    assert s["escalate"] and s["escalation_reasons"][0].startswith("classification failed")
    assert kinds(s) == ["create_contact", "add_note", "create_task"]


# ------------------------------------------------------------- URL stripping

async def test_urls_not_in_kb_are_stripped_from_drafts(make_graph):
    reply = GOOD_REPLY.replace("Hi Maya,", "Hi Maya, see https://evil.example/phish and contact refunds@evil-demo.example.")
    g, _, _ = make_graph([cls_json(), draft_json(reply)])
    s = await g.ainvoke(start_state(), cfg())
    assert "evil" not in s["offered_draft"] and "[link removed]" in s["offered_draft"]
    assert len(s["draft"]["removed_urls"]) == 2


async def test_kb_urls_are_kept(make_graph, retriever):
    import re
    url = re.search(r"[a-z0-9.-]*ledgerline-demo\.example", retriever.all_text).group(0)
    g, _, _ = make_graph([cls_json(), draft_json(GOOD_REPLY.replace("Hi Maya,", f"Hi Maya, see {url}."))])
    s = await g.ainvoke(start_state(), cfg())
    assert url in s["offered_draft"]


# ------------------------------------------------------------- CRM lookup

async def test_unknown_sender_creates_exactly_one_contact_first(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)])
    s = await g.ainvoke(start_state(live=True), cfg())
    assert kinds(s) == ["create_contact", "add_note"]
    c = s["plan"]["actions"][0]
    assert c["email"] == TICKET["from_email"] and c["name"] == "Maya Demo"
    s = await g.ainvoke(Command(resume={"decision": "approve"}), cfg())
    assert s["status"] == "executed"
    assert [t for t, _ in crm.write_calls] == ["create_contact", "add_note"]
    assert crm.write_calls[1][1]["contact_id"] == "C900"


async def test_known_sender_gets_note_on_existing_record(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)], crm=FakeCrm(existing=EXISTING))
    await g.ainvoke(start_state(live=True), cfg())
    s = await g.ainvoke(Command(resume={"decision": "approve"}), cfg())
    assert s["status"] == "executed"
    assert [(t, a["contact_id"]) for t, a in crm.write_calls] == [("add_note", "C123")]
    assert crm.search_calls == [TICKET["from_email"]]


async def test_lookup_failure_does_not_crash(make_graph):
    class Broken(FakeCrm):
        async def search(self, q):
            raise RuntimeError("down")
    g, _, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)], crm=Broken())
    s = await g.ainvoke(start_state(), cfg())
    assert "lookup failed" in s["lookup_note"] and s["__interrupt__"]


async def test_escalation_live_writes_note_and_task(make_graph):
    g, crm, _ = make_graph([cls_json(category="account_security")], crm=FakeCrm(existing=EXISTING))
    await g.ainvoke(start_state(live=True), cfg())
    s = await g.ainvoke(Command(resume={"decision": "approve"}), cfg())
    assert [t for t, _ in crm.write_calls] == ["add_note", "create_task"]
    assert crm.write_calls[1][1] == {"name": "Escalation: " + TICKET["subject"], "due_date": TODAY.isoformat(),
                                     "contact_id": "C123", "description": crm.write_calls[1][1]["description"]}


# ------------------------------------------------------------- approval

async def test_reject_makes_no_writes(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)])
    await g.ainvoke(start_state(live=True), cfg())
    s = await g.ainvoke(Command(resume={"decision": "reject"}), cfg())
    assert s["status"] == "rejected" and crm.writer_opened == 0


async def test_edit_draft_rebuilds_note(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)], crm=FakeCrm(existing=EXISTING))
    await g.ainvoke(start_state(live=True), cfg())
    s = await g.ainvoke(Command(resume={"decision": "edit", "draft": "Hi Maya, human-written answer."}), cfg())
    assert s["status"] == "executed" and s["draft_edited"]
    note = crm.write_calls[0][1]["note"]
    assert "edited by a human reviewer" in note and "human-written answer" in note


async def test_edit_plan_valid_and_invalid(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)], crm=FakeCrm(existing=EXISTING))
    s = await g.ainvoke(start_state(live=True), cfg())
    bad = {"actions": s["plan"]["actions"] + [{"action": "create_task", "contact_id": "C123", "name": "Call me",
                                                "due_date": "2026-11-13"}]}
    s = await g.ainvoke(Command(resume={"decision": "edit", "plan": bad}), cfg())
    assert s["__interrupt__"] and "edit rejected" in s["__interrupt__"][0].value["error"]
    other = {"actions": [{"action": "add_note", "contact_id": "SOMEONE-ELSE", "note": "x"}]}
    s = await g.ainvoke(Command(resume={"decision": "edit", "plan": other}), cfg())
    assert "other than the ticket sender" in s["__interrupt__"][0].value["error"]
    good = {"actions": [{"action": "add_note", "contact_id": "C123", "note": "Edited note."}]}
    s = await g.ainvoke(Command(resume={"decision": "edit", "plan": good}), cfg())
    assert s["status"] == "executed" and crm.write_calls == [("add_note", {"contact_id": "C123", "note": "Edited note."})]


async def test_unknown_decision_three_times_rejects(make_graph):
    g, crm, _ = make_graph([cls_json(), draft_json(GOOD_REPLY)])
    await g.ainvoke(start_state(live=True), cfg())
    for _ in range(2):
        s = await g.ainvoke(Command(resume={"decision": "yolo"}), cfg())
        assert s["__interrupt__"]
    s = await g.ainvoke(Command(resume={"decision": "yolo"}), cfg())
    assert s["status"] == "rejected" and crm.writer_opened == 0


# ------------------------------------------------------------- dry run and failures

async def test_dry_run_makes_zero_write_calls(make_graph):
    g, crm, audit = make_graph([cls_json(category="account_security")])
    await g.ainvoke(start_state(live=False), cfg())
    s = await g.ainvoke(Command(resume={"decision": "approve"}), cfg())
    assert s["status"] == "dry_run" and all(r["dry_run"] for r in s["results"])
    assert crm.write_calls == [] and crm.writer_opened == 0
    assert any(e["event"] == "execute" and e["write_calls"] == 0 for e in audit.events)


async def test_partial_failure_is_reported_not_retried(make_graph):
    g, crm, _ = make_graph([cls_json(category="account_security")], crm=FakeCrm(fail_on="add_note"))
    await g.ainvoke(start_state(live=True), cfg())
    s = await g.ainvoke(Command(resume={"decision": "approve"}), cfg())
    assert s["status"] == "partial"
    assert [t for t, _ in crm.write_calls] == ["create_contact", "add_note"]


async def test_llm_sees_ticket_and_kb_only_as_untrusted_data(retriever):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langgraph.checkpoint.memory import InMemorySaver
    from support_agent.audit import AuditLog
    from support_agent.graph import Deps, build_graph
    seen = []

    class Spy(FakeListChatModel):
        async def ainvoke(self, messages, *a, **k):
            seen.append(messages)
            return await super().ainvoke(messages, *a, **k)

    deps = Deps(model=Spy(responses=[cls_json(), draft_json(GOOD_REPLY)]), retriever=retriever, crm=FakeCrm(existing=EXISTING),
                audit=AuditLog(None), min_retrieval_score=0.0, provider="fake")
    s = await build_graph(deps, InMemorySaver()).ainvoke(start_state(), cfg())
    cls_user, draft_user = seen[0][1].content, seen[1][1].content
    assert "<untrusted_ticket>" in cls_user and TICKET["body"] in cls_user
    assert '<untrusted_kb id="webhooks#3">' in draft_user
    assert "C123" not in cls_user + draft_user  # CRM data never reaches the model
    assert s["__interrupt__"]
