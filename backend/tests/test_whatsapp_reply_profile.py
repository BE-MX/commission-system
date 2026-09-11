import json
from types import SimpleNamespace
import pytest
from app.whatsapp_translation.reply_profile import source_profile
from app.whatsapp_translation.errors import WhatsAppTranslationError


def binding(section, purpose='public_fact'):
    return dict(document_id=10, revision_id=20, section_index=section, content_hash='a'*64,
                policy_version='synthetic', purpose=purpose)


def test_release_profile_supplies_facts_missing_from_old_inline_config(tmp_path):
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps([binding(1), binding(2)]))
    settings = SimpleNamespace(WHATSAPP_REPLY_SOURCE_PROFILE=str(path), WHATSAPP_REPLY_SOURCE_BINDINGS=[binding(3, 'constraint')])
    assert [b.section_index for b in source_profile(settings)] == [1, 2, 3]
    settings.WHATSAPP_REPLY_SOURCE_BINDINGS.append(binding(2, 'blocked'))
    assert source_profile(settings)[1].purpose == 'blocked'


def test_missing_or_invalid_profile_never_silently_drops_facts(tmp_path):
    settings = SimpleNamespace(WHATSAPP_REPLY_SOURCE_PROFILE=str(tmp_path / 'missing'), WHATSAPP_REPLY_SOURCE_BINDINGS=[])
    with pytest.raises(WhatsAppTranslationError) as exc:
        source_profile(settings)
    assert exc.value.error_code == 'reply_configuration_invalid'


def test_explicit_custom_profile_can_disable_release_bindings():
    settings = SimpleNamespace(WHATSAPP_REPLY_SOURCE_PROFILE='', WHATSAPP_REPLY_SOURCE_BINDINGS=[binding(7)])
    assert [b.section_index for b in source_profile(settings)] == [7]


@pytest.mark.parametrize('value', [{}, '', None])
def test_non_list_profile_is_an_error_instead_of_inline_only(tmp_path, value):
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(value))
    settings = SimpleNamespace(WHATSAPP_REPLY_SOURCE_PROFILE=str(path), WHATSAPP_REPLY_SOURCE_BINDINGS=[binding(7)])
    with pytest.raises(WhatsAppTranslationError) as exc:
        source_profile(settings)
    assert exc.value.error_code == 'reply_configuration_invalid'
