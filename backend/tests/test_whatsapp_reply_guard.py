import pytest
from pydantic import ValidationError

from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.reply_guard import choose_language, safe_clarification, validate_output, validate_plan
from app.whatsapp_translation.reply_schemas import ReplyPlan
from tests.reply_support import encode, output, plan, request


SOURCES = [
    {"purpose": "constraint", "text": "Do not promise sample refunds or delivery dates."},
    {"purpose": "public_fact", "text": "Genius Weft has a thin seam."},
]


@pytest.mark.parametrize("unsafe", [
    "The price is $100.", "Your total is 200 EUR.", "We offer a 10% discount.",
    "We guarantee the quality.", "We can deliver in seven days.", "The sample is free shipping.",
    "I have escalated this case.", "We already checked your parcel.",
    "Our internal cost is confidential but here it is.", "Your customer tier is VIP.",
    "We have 200 in stock.", "Please transfer payment tomorrow.",
    "Sie bekommen kostenlose Muster.", "Wir garantieren die Lieferung.",
    "Wir liefern in sieben Tagen.", "Das ist unsere Gewinnmarge.",
    "Wir haben das bereits genehmigt.", "Die Ware ist auf Lager.",
    "There is a lifetime warranty for your purchase.",
    "We will reimburse your sample fee.",
    "The samples are complimentary.",
    "Wir erstatten Ihnen die Mustergebühr.",
])
def test_unsupported_promises_cannot_become_fillable_draft(unsafe):
    with pytest.raises(WhatsAppTranslationError):
        validate_output(encode(output(reply_text=unsafe, claims=[])), "en", SOURCES, request())


@pytest.mark.parametrize("bad_claim", [
    {"text": "Genius Weft has a thin seam.", "source_index": 5, "quote": "invented"},
    {"text": "Genius Weft has a thin seam.", "source_index": 0, "quote": "Do not promise sample refunds"},
    {"text": "Genius Weft has a thin seam.", "source_index": 1, "quote": "Invented evidence"},
    {"text": "Not in the draft", "source_index": 1, "quote": "Genius Weft has a thin seam."},
])
def test_claims_require_actual_public_source_and_exact_quote(bad_claim):
    with pytest.raises(WhatsAppTranslationError) as caught:
        validate_output(encode(output(claims=[bad_claim])), "en", SOURCES, request())
    assert caught.value.error_code == "reply_invalid_evidence"


def test_method_does_not_inherit_disclosure_permission():
    with pytest.raises(WhatsAppTranslationError):
        validate_output(encode(output()), "en", [SOURCES[0], {**SOURCES[1], "purpose": "method"}], request())


def test_valid_product_fact_citation_is_accepted():
    assert validate_output(encode(output()), "en", SOURCES, request()).status == "ready"


@pytest.mark.parametrize("text", ["Call +12345678901", "Email synthetic@example.invalid", "Open https://example.invalid", "<script>fake</script>", "Dear [customer name]"])
def test_contacts_links_and_placeholders_rejected(text):
    with pytest.raises(WhatsAppTranslationError):
        validate_output(encode(output(reply_text=text, claims=[])), "en", SOURCES, request())


def test_customer_product_dimension_can_be_repeated_but_old_seller_numbers_cannot():
    data = request(messages=[{"role": "customer", "text": "I need 20 inches."}])
    result = output(reply_text="You mentioned 20 inches. Which installation method do you prefer?", claims=[])
    assert validate_output(encode(result), "en", SOURCES, data).reply_text == result["reply_text"]
    with pytest.raises(WhatsAppTranslationError):
        validate_output(encode(result), "en", SOURCES, request(messages=[{"role": "salesperson", "text": "I offered 20 inches."}]))


@pytest.mark.parametrize("message", ["OK", "👍", "1234", "Okay", "Thanks"])
def test_short_acknowledgment_not_strong_language_evidence(message):
    data = request(messages=[{"role": "customer", "text": message}], fallback_language="de")
    assert choose_language(ReplyPlan.model_validate(plan()), data) == ("de", False)


def test_recent_meaningful_customer_language_and_explicit_override():
    data = request(messages=[{"role": "customer", "text": "Ich benötige eine leichte Tresse."}, {"role": "customer", "text": "OK"}])
    model_plan = ReplyPlan.model_validate(plan(reply_language="de"))
    assert choose_language(model_plan, data) == ("de", True)
    assert choose_language(model_plan, data.model_copy(update={"target_language": "fr"})) == ("fr", True)


def test_buyer_signal_cannot_cite_sellers_own_proposal():
    data = request(messages=[{"role": "salesperson", "text": "I suggest sending a sample."}])
    wrong = plan(evidence=[{"message_index": 0, "role": "salesperson", "kind": "buyer_action", "summary": "Customer accepted sample"}])
    with pytest.raises(WhatsAppTranslationError):
        validate_plan(encode(wrong), data)


@pytest.mark.parametrize("evidence", [
    {"message_index": 3, "role": "customer", "kind": "inference", "summary": "Missing message"},
    {"message_index": 0, "role": "salesperson", "kind": "seller_statement", "summary": "Wrong direction"},
])
def test_planner_message_references_must_exist_with_correct_direction(evidence):
    with pytest.raises(WhatsAppTranslationError):
        validate_plan(encode(plan(evidence=[evidence])), request())


@pytest.mark.parametrize("bad", ["not json", "```json\n{}\n```", "[]", '{"reply_text":"only one field"}'])
def test_malformed_model_output_fails_closed(bad):
    with pytest.raises(WhatsAppTranslationError):
        validate_output(bad, "en", SOURCES, request())


def test_schema_rejects_extra_identity_and_oversized_context():
    with pytest.raises(ValidationError):
        request(user_id=999)
    with pytest.raises(ValidationError):
        request(messages=[{"role": "customer", "text": "x" * 7000}] * 2)
    with pytest.raises(ValidationError):
        request(messages=[{"role": "customer", "text": "hello"}] * 21)


def test_german_request_cannot_receive_obvious_english_body():
    with pytest.raises(WhatsAppTranslationError) as caught:
        validate_output(encode(output(reply_language="de")), "de", SOURCES, request())
    assert caught.value.error_code == "reply_language_mismatch"


@pytest.mark.parametrize("language,text", [("en", "No thank you. Please stop contacting me."), ("de", "Nein danke. Bitte kontaktieren Sie mich nicht mehr.")])
def test_missing_knowledge_does_not_force_a_question_after_explicit_refusal(language, text):
    result = safe_clarification(language, request(messages=[{"role": "customer", "text": text}]))
    assert "?" not in result.reply_text
    assert result.missing_information == []
