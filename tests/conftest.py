import datetime as dt
import hashlib
import json
import math
import re
from contextlib import asynccontextmanager

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver

from support_agent.audit import AuditLog
from support_agent.config import ROOT
from support_agent.graph import Deps, build_graph
from support_agent.kb import Retriever, build_index, load_kb

KB_DIR = ROOT / "kb"
TODAY = dt.date(2026, 11, 13)


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors: no Ollama needed."""
    name = "fake-embed"
    dim = 64

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class FakeWriter:
    def __init__(self, crm):
        self.crm = crm

    async def call(self, tool, args):
        self.crm.write_calls.append((tool, args))
        if self.crm.fail_on == tool:
            raise RuntimeError(f"boom with key {self.crm.secret}")
        n = len(self.crm.write_calls)
        return {"create_contact": {"contact_id": "C900"}, "add_note": {"note_id": f"N{n}"},
                "create_task": {"task_id": f"T{n}"}}[tool]


class FakeCrm:
    """Mocked MCP client: records every call; writes only through writer()."""

    def __init__(self, existing=None, fail_on=None, secret=""):
        self.existing = existing or []
        self.search_calls, self.write_calls = [], []
        self.writer_opened = 0
        self.fail_on, self.secret = fail_on, secret

    async def search(self, query):
        self.search_calls.append(query)
        return [r for r in self.existing if query.lower() in json.dumps(r).lower()]

    @asynccontextmanager
    async def writer(self):
        self.writer_opened += 1
        yield FakeWriter(self)


TICKET = {"id": "T-9001", "from_name": "Maya Demo", "from_email": "maya.demo@brightpaws-demo.example",
          "subject": "How do I verify webhook signatures?",
          "body": "Hi, we added a webhook endpoint. How do I check the X-Ledgerline-Signature header is genuine? Thanks, Maya",
          "received_at": "2026-11-10T09:00:00Z"}


def cls_json(category="how_to", urgency="normal", sentiment="neutral", **flags):
    return json.dumps({"category": category, "urgency": urgency, "sentiment": sentiment,
                       "summary": "Customer asks how to verify webhook signatures.", **flags})


def draft_json(reply, can_answer=True):
    return json.dumps({"can_answer": can_answer, "reply": reply})


GOOD_REPLY = ("Hi Maya,\n\nEach request carries an X-Ledgerline-Signature header with an HMAC-SHA256 of the raw body [webhooks#3]. "
              "As the article says, \"Reject any request whose signature does not match.\" [webhooks#3]\n\n"
              "[Your name], Ledgerline (Demo) Support")


@pytest.fixture(scope="session")
def kb_index(tmp_path_factory):
    path = tmp_path_factory.mktemp("kb") / "kb.sqlite"
    build_index(load_kb([KB_DIR]), FakeEmbedder(), path)
    return path


@pytest.fixture
def retriever(kb_index):
    r = Retriever(kb_index, FakeEmbedder())
    yield r
    r.close()


@pytest.fixture
def make_graph(tmp_path, retriever):
    def _make(responses, crm=None, audit_dir=None, secrets=(), min_score=0.0):
        crm = crm or FakeCrm()
        audit = AuditLog(audit_dir or tmp_path / "audit", list(secrets))
        deps = Deps(model=FakeListChatModel(responses=list(responses)), retriever=retriever, crm=crm, audit=audit,
                    min_retrieval_score=min_score, provider="fake", today=lambda: TODAY)
        return build_graph(deps, InMemorySaver()), crm, audit
    return _make


def cfg(tid="t1"):
    return {"configurable": {"thread_id": tid}}


def start_state(ticket=None, live=False, run_id="t1"):
    return {"run_id": run_id, "raw_ticket": dict(ticket or TICKET), "live": live, "timings": {}}


EXISTING = [{"contact_id": "C123", "email": TICKET["from_email"], "name": "Maya Demo", "is_company": False}]
