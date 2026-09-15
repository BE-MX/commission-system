"""Synthetic text only: normalization must preserve every answer."""
import pytest
from app.whatsapp_translation.reply_segments import browser_length, prepare_segments


@pytest.mark.parametrize('parts', [
    ['First answer. ' * 32 + 'Final answer.'],
    ['First.', 'Second.', 'Third.', 'Fourth.'],
    ['Answer 🙂. ' * 39],
    ['问题的回答。' * 80],
])
def test_normalization_preserves_words_and_order_with_browser_limits(parts):
    result = prepare_segments(parts)
    assert result and len(result) <= 3
    assert all(browser_length(part) <= 400 for part in result)
    assert ''.join(''.join(result).split()) == ''.join(''.join(parts).split())


@pytest.mark.parametrize('parts', [['https://example.com/' + 'x' * 500], ['word ' * 300]])
def test_content_that_cannot_fit_is_not_truncated(parts):
    assert prepare_segments(parts) is None
