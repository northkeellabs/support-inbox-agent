"""Pydantic models: the ticket, the LLM's structured outputs, and the action plan.

The action plan is the only thing the execute node will act on. It is strict:
three allowed action types, at most one of each, capped field lengths, no
unknown fields, and a task only for escalations. Anything else fails validation
and nothing is written.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

EMAIL_RE = r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$"
Category = Literal["how_to", "billing", "bug", "account_security", "feature_request", "spam"]
CATEGORIES = ("how_to", "billing", "bug", "account_security", "feature_request", "spam")
NOTE_MAX = 4000
TASK_PREFIX = "Escalation: "


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------ input

class Ticket(Strict):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    from_name: str = Field(min_length=1, max_length=120)
    from_email: str = Field(max_length=254, pattern=EMAIL_RE)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    received_at: dt.datetime


# --------------------------------------------------------- LLM outputs

class Classification(Strict):
    category: Category
    urgency: Literal["low", "normal", "high"]
    sentiment: Literal["positive", "neutral", "negative"]
    summary: str = Field(min_length=1, max_length=300)
    refund_or_dispute: bool = False
    legal_threat: bool = False
    requests_other_customer_data: bool = False


class Draft(Strict):
    can_answer: bool
    reply: str = Field(default="", max_length=3000)


# --------------------------------------------------------- action plan

class CreateContact(Strict):
    action: Literal["create_contact"]
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=254, pattern=EMAIL_RE)
    background_info: str | None = Field(default=None, max_length=500)


class AddNote(Strict):
    action: Literal["add_note"]
    contact_id: str | None = Field(default=None, max_length=40, description="Existing contact id from lookup; None = the contact created by this plan")
    note: str = Field(min_length=1, max_length=NOTE_MAX)


class CreateTask(Strict):
    action: Literal["create_task"]
    contact_id: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=len(TASK_PREFIX) + 1, max_length=200)
    due_date: dt.date
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _escalation_only(self) -> "CreateTask":
        if not self.name.startswith(TASK_PREFIX):
            raise ValueError(f"task name must start with {TASK_PREFIX!r} (tasks are only for escalations)")
        return self


Action = Annotated[Union[CreateContact, AddNote, CreateTask], Field(discriminator="action")]
ALLOWED_ACTIONS = ("create_contact", "add_note", "create_task")


class ActionPlan(Strict):
    actions: list[Action] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _shape(self) -> "ActionPlan":
        kinds = [a.action for a in self.actions]
        for k in ALLOWED_ACTIONS:
            if kinds.count(k) > 1:
                raise ValueError(f"at most one {k} per ticket (got {kinds.count(k)})")
        if self.actions and "add_note" not in kinds:
            raise ValueError("a non-empty plan must log the ticket with add_note")
        if "create_contact" in kinds and kinds[0] != "create_contact":
            raise ValueError("create_contact must come first")
        creates = "create_contact" in kinds
        for a in self.actions:
            if isinstance(a, (AddNote, CreateTask)) and a.contact_id is None and not creates:
                raise ValueError(f"{a.action} has no contact_id and the plan creates no contact")
            if isinstance(a, (AddNote, CreateTask)) and a.contact_id is not None and creates:
                raise ValueError("a plan that creates the contact may not also target an existing contact")
        return self

    def contact_ids(self) -> set[str]:
        return {a.contact_id for a in self.actions if isinstance(a, (AddNote, CreateTask)) and a.contact_id}

    def created_emails(self) -> set[str]:
        return {a.email.lower() for a in self.actions if isinstance(a, CreateContact)}
