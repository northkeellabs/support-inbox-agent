"""FastAPI webhook: POST /tickets, GET /pending, POST /approve/{run_id}.

Every endpoint needs the X-Support-Secret header (SUPPORT_WEBHOOK_SECRET). Live CRM
writes are a server setting (SUPPORT_LIVE=1), never a request parameter.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ValidationError

from .config import Settings, webhook_secret
from .runtime import new_run_id, open_runner
from .schema import Ticket

MAX_BODY = 32 * 1024
RATE_PER_MIN = 30


class ApprovalIn(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    plan: dict | None = None
    draft: str | None = None


def create_app(settings: Settings | None = None, runner_factory=None) -> FastAPI:
    settings = settings or Settings()
    live = os.environ.get("SUPPORT_LIVE", "") == "1"
    hits: dict[str, deque] = defaultdict(deque)
    sem = asyncio.Semaphore(1)  # one local-LLM run at a time
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = runner_factory or (lambda: open_runner(settings))
        async with factory() as runner:
            app.state.runner = runner
            yield

    app = FastAPI(title="support-inbox-agent", version="0.1.0", lifespan=lifespan)

    async def guard(request: Request, x_support_secret: str = Header(default="")) -> None:
        secret = webhook_secret()
        if not secret:
            raise HTTPException(503, "SUPPORT_WEBHOOK_SECRET is not configured")
        if not hmac.compare_digest(x_support_secret.encode(), secret.encode()):
            raise HTTPException(401, "bad or missing X-Support-Secret")
        ip = request.client.host if request.client else "?"
        q, now = hits[ip], time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MIN:
            raise HTTPException(429, "rate limit")
        q.append(now)

    @app.post("/tickets", status_code=202, dependencies=[Depends(guard)])
    async def post_ticket(request: Request) -> dict:
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413, "body too large")
        try:
            ticket = Ticket.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(422, [e["msg"] for e in exc.errors()][:5]) from None
        run_id = new_run_id(ticket.id)

        async def work():
            async with sem:
                await app.state.runner.start(ticket.model_dump(mode="json"), live=live, run_id=run_id)

        t = asyncio.create_task(work())
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        return {"run_id": run_id, "status": "accepted", "live": live}

    @app.get("/pending", dependencies=[Depends(guard)])
    async def pending() -> list[dict]:
        out = []
        for run_id, ticket_id, created in app.state.runner.index.pending():
            p = await app.state.runner.pending_payload(run_id)
            if p:
                out.append({"run_id": run_id, "ticket_id": ticket_id, "created": created,
                            "classification": p.get("classification"), "escalate": p.get("escalate"),
                            "escalation_reasons": p.get("escalation_reasons"), "draft": p.get("draft"),
                            "plan": p.get("plan"), "live": p.get("live"), "error": p.get("error")})
        return out

    @app.post("/approve/{run_id}", dependencies=[Depends(guard)])
    async def approve(run_id: str, body: ApprovalIn) -> dict:
        if await app.state.runner.pending_payload(run_id) is None:
            raise HTTPException(404, "run is not waiting for approval")
        res = await app.state.runner.resume(run_id, body.model_dump(exclude_none=True))
        st = res["state"]
        return {"run_id": run_id, "status": res["status"], "results": st.get("results"),
                "error": (res.get("approval") or {}).get("error")}

    return app
