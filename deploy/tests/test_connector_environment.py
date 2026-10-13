"""Preflight must see the same precedence as NSSM followed by dotenv."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_release import connector_environment


def test_inherited_environment_is_not_overridden_by_dotenv():
    assert connector_environment({'WHATSAPP_PROVIDER': 'unsupported'}, {'WHATSAPP_PROVIDER': 'baileys'}, None, []) == {'WHATSAPP_PROVIDER': 'unsupported'}


def test_nssm_base_replaces_inherited_and_extra_wins():
    result = connector_environment({'UNEXPECTED': 'inherited'}, {'ARK_API_BASE_URL': 'file'},
        ['WHATSAPP_PROVIDER=base'], ['WHATSAPP_PROVIDER=baileys', 'ARK_API_BASE_URL=service'])
    assert result == {'WHATSAPP_PROVIDER': 'baileys', 'ARK_API_BASE_URL': 'service'}


def test_dotenv_supplies_missing_settings_without_null_values():
    assert connector_environment({}, {'KEY': 'value', 'UNSET': None}, None, []) == {'KEY': 'value'}
