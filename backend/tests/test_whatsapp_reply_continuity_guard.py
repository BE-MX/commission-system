from uuid import uuid4

import pytest

from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.reply_guard import validate_output, validate_plan
from app.whatsapp_translation.reply_schemas import ReplyPlan
from tests.reply_support import encode, output, plan, request


def observation(kind="need", status="tentative", quotes=("20 units",), human_note=""):
    return {"id": str(uuid4()), "kind": kind, "status": status, "summary": quotes[-1], "human_note": human_note,
            "evidence": [{"quote": q, "role": "customer" if kind == "need" else "salesperson"} for q in quotes]}


def check(text, payload, memory=(), planner=None):
    return validate_output(encode(output(reply_text=text, claims=[])), "en", [], payload, memory=memory, plan=planner)


def test_customer_sku_and_unit_quantities_can_be_repeated_without_deriving_total():
    payload = request(messages=[{"role": "customer", "text": "Around 20 SKUs, 20 units each."}])
    assert check("Understood, around 20 SKUs with 20 units each.", payload).status == "ready"
    with pytest.raises(WhatsAppTranslationError) as caught:
        check("Understood, 400 units in total.", payload)
    assert caught.value.error_code == "reply_unsupported_number"


def test_prior_need_allows_remembered_units_but_seller_claim_does_not():
    payload = request(messages=[{"role": "customer", "text": "Please show the options."}])
    assert check("Understood, 20 units initially.", payload, [observation()]).status == "ready"
    with pytest.raises(WhatsAppTranslationError):
        check("Understood, 20 units initially.", payload, [observation(kind="commitment", status="mentioned")])


def test_old_visible_quantity_does_not_override_new_evidence():
    payload = request(messages=[{"role": "customer", "text": "I want 20 units."}, {"role": "customer", "text": "Actually 10 units."}])
    memory = [observation(quotes=("20 units", "10 units"))]
    assert check("Understood, 10 units initially.", payload, memory).status == "ready"
    with pytest.raises(WhatsAppTranslationError):
        check("Understood, 20 units initially.", payload, memory)


def test_human_verified_quantity_replaces_old_value():
    payload = request(messages=[{"role": "customer", "text": "Please show the options."}])
    memory = [observation(status="human_confirmed", human_note="10 units")]
    assert check("Understood, 10 units initially.", payload, memory).status == "ready"
    with pytest.raises(WhatsAppTranslationError):
        check("Understood, 20 units initially.", payload, memory)


def test_answered_question_is_not_asked_again():
    payload = request(messages=[{"role": "salesperson", "text": "Which installation method do you prefer?"}, {"role": "customer", "text": "Sew-in."}])
    p = ReplyPlan.model_validate(plan(answered_questions=[0], unanswered_requests=[], evidence=[]))
    with pytest.raises(WhatsAppTranslationError) as caught:
        check("Which installation method do you prefer?", payload, planner=p)
    assert caught.value.error_code == "reply_repeated_question"


@pytest.mark.parametrize("fields", [{"answered_questions": [0]}, {"unanswered_requests": [40]}, {"unanswered_requests": [0, 0]}])
def test_question_worklist_indices_have_correct_direction_and_bounds(fields):
    with pytest.raises(WhatsAppTranslationError):
        validate_plan(encode(plan(**fields)), request())
