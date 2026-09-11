"""Conservative structural/evidence guards, not a claim of semantic proof."""

import json
import re
from difflib import SequenceMatcher

from pydantic import ValidationError

from app.whatsapp_translation.constants import SUPPORTED_TARGET_LANGUAGES
from app.whatsapp_translation.reply_schemas import ReplyOutput, ReplyPlan
from app.whatsapp_translation.reply_state import error


RISK_FLAGS = {
    "limited_context", "media_not_read", "language_uncertain", "knowledge_unavailable",
    "policy_confirmation_required", "conflicting_evidence", "historical_commitment",
    "internal_confirmation_required", "alternative_not_supported", "no_public_facts",
}
CONTACT = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")
SPECIFICATION = re.compile(r"\d+(?:[.,]\d+)?\s*(?:inch(?:es)?\b|in\b|cm\b|mm\b|g\b|grams?\b|Zoll\b|英寸|厘米|SKUs?\b|units?\b|pieces?\b|pcs\b|models?\b|件|款)", re.I)
LINK_OR_MARKUP = re.compile(r"https?://|www\.|<[^>]+>|\[(?:name|price|date|customer|姓名|价格|日期)[^\]]*\]", re.I)
UNSAFE = re.compile(
    r"[$€£¥]|\b(?:USD|EUR|GBP|RMB)\b|\d\s*%|"
    r"\b(?:free samples?|free shipping|full refund|money.back|guarantee[ds]?|guaranteed|"
    r"lifetime warranty|warrant(?:y|ies)|"
    r"reimburse\w*|complimentary|at no (?:cost|charge)|at our expense|"
    r"in stock|lowest price|exclusive rights|already (?:sent|checked|escalated|approved)|"
    r"(?:we|I) (?:have|has|had) (?:sent|checked|escalated|approved)|"
    r"(?:ships?|deliver(?:y|ed)?|refund|discount) (?:within|in|of|by)|"
    r"profit margin|internal cost|approval threshold|customer tier)\b|"
    r"\b(?:kostenlose[snmr]? (?:Muster|Versand)|volle Rückerstattung|garantier\w*|"
    r"lebenslange Garantie|"
    r"erstatten|erstatte|erstattet|gebührenfrei|gratis|"
    r"auf Lager|bereits (?:gesendet|geprüft|eskaliert|genehmigt)|Einkaufspreis|Gewinnmarge|"
    r"Genehmigungsgrenze|Kundenklassifizierung)\b|"
    r"免费|包邮|全额退款|保证|保證|已(?:经)?(?:查到|查询|升级|批准|建单|发出)|"
    r"底价|底價|内部成本|內部成本|审批阈值|利润率|客户分级",
    re.I,
)
COMMITMENT = re.compile(
    r"\b(?:we|I)\s+(?:(?:will|can|shall|would)\s+)?(?:refund|waive|deduct|credit|cover)\b|"
    r"\b(?:sample fee|sample cost|shipping cost)\b[^.!?]{0,80}\b(?:return\w*|refund\w*|deduct\w*|waiv\w*)\b|"
    r"\b(?:wir|ich)\s+(?:(?:werden|können|kann)\s+)?(?:übernehmen|erstatten|erlassen)\b", re.I,
)
DYNAMIC_TIME = re.compile(
    r"\b(?:tomorrow|next week|next month|today|morgen|nächste[nr]? Woche|heute|"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+) (?:days?|weeks?|months?|years?)|"
    r"(?:ein|zwei|drei|vier|fünf|sechs|sieben|acht|\d+) (?:Tage[n]?|Woche[n]?|Monate[n]?|Jahre[n]?))\b|"
    r"明天|本周|下周|\d+[天日周月年]", re.I,
)


def parse_json(content, schema):
    try:
        if not isinstance(content, str) or len(content) > 16000:
            raise ValueError("invalid output size")
        return schema.model_validate(json.loads(content))
    except (ValueError, TypeError, ValidationError):
        # Expected model validation failure; never include raw ValidationError/input.
        raise error("reply_invalid_response", 502) from None


def validate_plan(content, request) -> ReplyPlan:
    plan = parse_json(content, ReplyPlan)
    if plan.reply_language not in SUPPORTED_TARGET_LANGUAGES:
        raise error("reply_invalid_response", 502)
    for item in plan.evidence:
        if item.message_index >= len(request.messages) or request.messages[item.message_index].role != item.role:
            raise error("reply_invalid_evidence", 502)
        if item.kind in {"confirmed_need", "buyer_action"} and item.role != "customer":
            raise error("reply_invalid_evidence", 502)
    for indices, role in ((plan.unanswered_requests, "customer"), (plan.answered_questions, "salesperson")):
        if len(indices) != len(set(indices)) or any(index < 0 or index >= len(request.messages) or request.messages[index].role != role for index in indices):
            raise error("reply_invalid_evidence", 502)
    if plan.action.kind == "close" and plan.action.question:
        raise error("reply_invalid_response", 502)
    return plan


def choose_language(plan: ReplyPlan, request) -> tuple[str, bool]:
    if request.target_language != "auto":
        return request.target_language, True
    meaningful = [message.text for message in request.messages if message.role == "customer"
                  and len(re.findall(r"[^\W\d_]", message.text, re.UNICODE)) >= 4
                  and message.text.strip().casefold() not in {"okay", "thanks", "thank you", "danke"}]
    if not meaningful or not plan.language_confident:
        return request.fallback_language, False
    return plan.reply_language, True


def _script_matches(text: str, language: str) -> bool:
    cjk = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff]", text))
    if language not in {"zh-CN", "ja"} and cjk:
        return False
    if language in {"zh-CN", "ja"} and not cjk:
        return False
    if language == "ar" and not re.search(r"[\u0600-\u06ff]", text):
        return False
    # Detect obvious long English/German swaps, but do not pretend this proves
    # language correctness. Short texts and related languages require evaluation.
    words = re.findall(r"\b\w+\b", text.casefold())
    if len(words) >= 8 and language in {"en", "de"}:
        english = sum(word in {"the", "you", "your", "would", "could", "please", "which", "with", "what"} for word in words)
        german = sum(word in {"sie", "ihre", "ihren", "welche", "welchen", "können", "möchten", "bitte", "und", "für"} for word in words)
        if language == "de" and english >= 2 and german == 0:
            return False
        if language == "en" and german >= 2 and english == 0:
            return False
    return True


def validate_output(content, language: str, sources: list[dict], request, *, memory=(), plan=None) -> ReplyOutput:
    output = parse_json(content, ReplyOutput)
    if output.reply_language != language or not _script_matches(output.reply_text, language):
        raise error("reply_language_mismatch", 502)
    if set(output.risk_flags) - RISK_FLAGS:
        raise error("reply_invalid_response", 502)
    all_text = " ".join([output.reply_text, output.meaning_zh, output.rationale_zh, *output.missing_information])
    if CONTACT.search(all_text) or LINK_OR_MARKUP.search(all_text):
        raise error("reply_unsafe_response", 502)
    if UNSAFE.search(output.reply_text) or DYNAMIC_TIME.search(output.reply_text) or COMMITMENT.search(output.reply_text):
        raise error("reply_unsafe_response", 502)
    for claim in output.claims:
        if claim.source_index >= len(sources):
            raise error("reply_invalid_evidence", 502)
        source = sources[claim.source_index]
        if source["purpose"] != "public_fact" or claim.quote not in source["text"] or claim.text not in output.reply_text:
            raise error("reply_invalid_evidence", 502)
    # Obvious commercial factual assertions must be explicitly covered, not just
    # accompanied by an unrelated citation elsewhere in the response.
    fact_pattern = re.compile(
        r"\b(?:we|our|this|these|it|hair|weft|tape|product|seam)\b.{0,45}\b(?:is|are|has|have|uses?|lasts?|contains?|offers?)\b|"
        r"\b(?:wir|unser\w*|diese\w*|haar\w*|tresse\w*|naht)\b.{0,45}\b(?:ist|sind|hat|haben|verwenden|hält)\b|"
        r"我们(?:的)?|产品(?:是|有)|发帘(?:是|有)", re.I,
    )
    for sentence in re.split(r"(?<=[.!?。！？])\s*", output.reply_text):
        if not sentence or sentence.rstrip().endswith(("?", "？")):
            continue
        if fact_pattern.search(sentence) and not any(claim.text in sentence for claim in output.claims):
            raise error("reply_missing_evidence", 502)
    # Quantities may repeat a customer's product specification, never a seller's
    # old quote or draft intent. A number alone is not evidence for a new claim.
    customer_specs = " ".join(message.text for message in request.messages if message.role == "customer")
    # Only the current evidence of an active customer need, not superseded values,
    # seller promises or generated summaries, can supply a remembered quantity.
    customer_specs += " " + " ".join(
        item["evidence"][-1]["quote"] for item in memory
        if item["kind"] == "need" and item["status"] in {"confirmed", "tentative"}
        and item["evidence"] and item["evidence"][-1]["role"] == "customer"
    )
    customer_specs += " " + " ".join(item["human_note"] for item in memory
                                       if item["kind"] == "need" and item["status"] == "human_confirmed")
    # An older quote still appearing in the visible window does not revive a
    # superseded value in that same need. Independent active needs can share it.
    retired_specs, active_specs = set(), set()
    for item in memory:
        if item["kind"] != "need" or not item["evidence"]:
            continue
        active_text = item["human_note"] if item["status"] == "human_confirmed" else item["evidence"][-1]["quote"]
        if item["status"] != "cancelled":
            active_specs.update(match.group().casefold() for match in SPECIFICATION.finditer(active_text))
        historical = item["evidence"] if item["status"] in {"cancelled", "human_confirmed"} else item["evidence"][:-1]
        retired_specs.update(match.group().casefold() for source in historical for match in SPECIFICATION.finditer(source["quote"]))
    for match in re.finditer(r"\d+(?:[.,]\d+)?", output.reply_text):
        rest = output.reply_text[match.end():]
        unit = re.match(r"\s*(?:inch(?:es)?\b|in\b|cm\b|mm\b|g\b|grams?\b|Zoll\b|英寸|厘米|SKUs?\b|units?\b|pieces?\b|pcs\b|models?\b|件|款)", rest, re.I)
        specification = match.group() + (unit.group() if unit else "")
        if not unit or specification.casefold() not in customer_specs.casefold() or specification.casefold() in retired_specs - active_specs:
            raise error("reply_unsupported_number", 502)
    if plan is not None:
        answered = [request.messages[index].text for index in plan.answered_questions]
        answered += [entry["evidence"][0]["quote"] for entry in memory
                     if entry["kind"] == "question" and entry["status"] in {"answered", "human_completed"} and entry["evidence"]]
        normalize = lambda text: re.sub(r"[^\w\s]", "", text.casefold()).strip()
        questions = re.findall(r"[^.!?。！？]*[?？]", output.reply_text)
        if any(SequenceMatcher(None, normalize(question), normalize(previous)).ratio() >= 0.82
               for question in questions for previous in answered):
            raise error("reply_repeated_question", 502)
        if plan.action.kind == "close" and questions:
            raise error("reply_invalid_response", 502)
    # A source may guide strategy, but its internal wording must not be copied to
    # the external draft. Cross-language disclosure remains a semantic test gate.
    normalized_reply = re.sub(r"\s+", " ", output.reply_text).casefold()
    for source in sources:
        if source["purpose"] == "public_fact":
            continue
        for phrase in re.split(r"[。.!?\n]", source["text"]):
            phrase = re.sub(r"\s+", " ", phrase.strip()).casefold()
            if len(phrase) >= 20 and phrase in normalized_reply:
                raise error("reply_internal_disclosure", 502)
    return output


SAFE_CLARIFICATION = {
    "en": "Could you clarify the main point you would like us to check?",
    "de": "Könnten Sie bitte erläutern, welchen Punkt wir für Sie prüfen sollen?",
    "zh-CN": "请问您最希望我们核实的是哪一点？",
    "es": "¿Podría aclarar qué punto le gustaría que revisáramos?",
    "fr": "Pourriez-vous préciser le point que vous souhaitez que nous vérifiions ?",
    "ar": "هل يمكنك توضيح النقطة التي ترغب في أن نتحقق منها؟",
    "ja": "どの点を確認してほしいか、教えていただけますか？",
    "nl": "Kunt u verduidelijken welk punt u graag door ons wilt laten controleren?",
    "sv": "Kan du förtydliga vilken punkt du vill att vi kontrollerar?",
}


def safe_clarification(language: str, request=None) -> ReplyOutput:
    customer_text = next((message.text for message in reversed(request.messages) if message.role == "customer"), "") if request else ""
    stop = re.search(r"(?:^|[.!?]\s*|please\s+)stop (?:contacting|messaging)|do not contact|don't contact|kontaktieren Sie mich nicht mehr|不要再联系|请勿再联系", customer_text, re.I)
    if stop:
        closing = {
            "en": "Understood. I respect your request and will not contact you again.",
            "de": "Verstanden. Ich respektiere Ihren Wunsch und werde Sie nicht mehr kontaktieren.",
            "zh-CN": "明白，我尊重您的意愿，不再联系您。",
            "es": "Entendido. Respeto su decisión y no volveré a contactarle.",
            "fr": "Bien compris. Je respecte votre demande et ne vous recontacterai pas.",
            "ar": "مفهوم. أحترم طلبك ولن أتواصل معك مجددًا.",
            "ja": "承知しました。ご意向を尊重し、今後の連絡を控えます。",
            "nl": "Begrepen. Ik respecteer uw verzoek en zal geen contact meer opnemen.",
            "sv": "Förstått. Jag respekterar din önskan och kontaktar dig inte igen.",
        }
        return ReplyOutput(
            status="needs_confirmation", reply_language=language, reply_text=closing[language],
            meaning_zh="尊重客户停止联系的要求，不再联系。",
            rationale_zh="客户已明确终止联系，不再追问或提出替代销售方案。",
            risk_flags=["knowledge_unavailable"], missing_information=[],
        )
    return ReplyOutput(
        status="needs_confirmation", reply_language=language, reply_text=SAFE_CLARIFICATION[language],
        meaning_zh="请客户说明最希望我们核实的要点。",
        rationale_zh="本轮缺少可用的必需知识约束，只提供不含产品或商务承诺的澄清。",
        risk_flags=["knowledge_unavailable", "policy_confirmation_required"],
        missing_information=["请知识负责人核验本轮来源用途及必需政策；无可靠依据前不作产品或商务承诺。"],
    )
