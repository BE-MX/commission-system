from collections import Counter

from scripts.whatsapp_reply_cases import generate_cases
from tests.reply_support import request


def test_semantic_suite_has_thirty_bilingual_distinct_scenarios():
    cases = generate_cases()
    assert len(cases) == 30
    assert Counter(case.language for case in cases) == {"en": 15, "de": 15}
    assert len({case.case_id for case in cases}) == 30
    for case in cases:
        assert case.review_criteria
        parsed = request(messages=[{"role": role, "text": text} for role, text in case.messages], fallback_language=case.language, style=case.style,
                         context_scope={"requested_limit": 20, "omitted_media": case.omitted_media})
        assert parsed.messages
