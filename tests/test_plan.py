import pytest
from pydantic import ValidationError

from support_agent.graph import check_plan_targets
from support_agent.schema import NOTE_MAX, ActionPlan, Ticket

NOTE = {"action": "add_note", "contact_id": "C1", "note": "n"}
TASK = {"action": "create_task", "contact_id": "C1", "name": "Escalation: refund", "due_date": "2026-11-10"}
CONTACT = {"action": "create_contact", "name": "Maya Demo", "email": "maya@x-demo.example"}


def test_valid_plans():
    ActionPlan.model_validate({"actions": [NOTE]})
    ActionPlan.model_validate({"actions": [NOTE, TASK]})
    ActionPlan.model_validate({"actions": [CONTACT, {**NOTE, "contact_id": None}, {**TASK, "contact_id": None}]})
    ActionPlan.model_validate({"actions": []})


@pytest.mark.parametrize("actions", [
    [NOTE, NOTE],                                             # duplicate action
    [NOTE, TASK, TASK],                                       # duplicate task
    [NOTE, TASK, CONTACT, NOTE],                              # more than 3
    [TASK],                                                   # every plan must log a note
    [{**NOTE, "contact_id": None}],                           # no contact and none created
    [{**NOTE, "contact_id": None}, CONTACT],                  # create_contact must be first
    [CONTACT, NOTE],                                          # creates a contact but targets another
    [NOTE, {**TASK, "name": "Call the customer"}],            # tasks only for escalations
    [{**NOTE, "note": "x" * (NOTE_MAX + 1)}],                 # note too long
    [{**NOTE, "send_email": True}],                           # unknown field
    [{"action": "delete_contact", "contact_id": "C1"}],       # unknown action
    [NOTE, {**TASK, "name": "Escalation: " + "x" * 200}],     # task name too long
])
def test_invalid_plans_rejected(actions):
    with pytest.raises(ValidationError):
        ActionPlan.model_validate({"actions": actions})


def test_plan_may_only_target_the_sender():
    check_plan_targets(ActionPlan.model_validate({"actions": [NOTE]}), "C1", "maya@x-demo.example")
    with pytest.raises(ValueError):
        check_plan_targets(ActionPlan.model_validate({"actions": [NOTE]}), "C2", "maya@x-demo.example")
    new = ActionPlan.model_validate({"actions": [CONTACT, {**NOTE, "contact_id": None}]})
    check_plan_targets(new, None, "maya@x-demo.example")
    with pytest.raises(ValueError):
        check_plan_targets(new, None, "someone.else@x-demo.example")
    with pytest.raises(ValueError):
        check_plan_targets(new, "C1", "maya@x-demo.example")  # sender exists: no new contact allowed


def test_ticket_schema():
    t = {"id": "T-1", "from_name": "A", "from_email": "a@b-demo.example", "subject": "s", "body": "b",
         "received_at": "2026-11-10T09:00:00Z"}
    Ticket.model_validate(t)
    for bad in ({"from_email": "nope"}, {"body": "x" * 9000}, {"id": "../etc"}, {"extra": 1}):
        with pytest.raises(ValidationError):
            Ticket.model_validate({**t, **bad})
