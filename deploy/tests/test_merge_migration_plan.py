"""Both preflight paths must report every migration Alembic will execute, without a DB."""
import ast
from pathlib import Path
import sys

import pytest
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


@pytest.mark.parametrize('current_revision', ['150_domestic_item_guest', '146_expo_beautify_prompt', '145_domestic_order_guest', '152_shipping_media_recall', '151_customer_media_tags', '163_okki_presence_days', '183_portal_password_login', '185_announcement_push_option', '186_portal_announcement_merge', '194_navigation_preferences'])
@pytest.mark.parametrize('filename', ['remote_backend.py', 'migration_runner.py'])
def test_preflight_pending_matches_alembic_upgrade(current_revision, filename):
    script = ScriptDirectory(str(ROOT / 'backend/alembic'))
    head = script.get_current_head()
    tree = ast.parse((ROOT / 'deploy' / filename).read_text(encoding='utf-8'))
    if filename == 'remote_backend.py':
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'schema_check')
        code = next(node.value.value for node in function.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'code' for target in node.targets))
        tree = ast.parse(code)
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'pending' for target in node.targets))
    pending = eval(compile(ast.Expression(assignment.value), filename, 'eval'), {
        'script': script, 'heads': [head], 'current': [current_revision], 'request': {'schema': head},
    })
    if filename == 'remote_backend.py':
        pending.reverse()
    actual = [step.revision.revision for step in script._upgrade_revs(head, current_revision)]
    assert pending == actual
    if current_revision == '163_okki_presence_days':
        assert pending[0] == '164_battle_posters'
        assert pending[-1] == head
    if current_revision == '150_domestic_item_guest':
        assert pending[:2] == ['146_expo_beautify_prompt', '152_shipping_media_recall']
        assert pending[-1] == head


def test_deployed_password_schema_only_runs_new_business_migrations():
    script = ScriptDirectory(str(ROOT / 'backend/alembic'))
    assert script.get_heads() == ['195_main_portal_merge']
    actual = [step.revision.revision for step in script._upgrade_revs('186_portal_announcement_merge', '183_portal_password_login')]
    assert actual == ['184_domestic_request_withdraw', '185_announcement_push_option', '186_portal_announcement_merge']
    assert script.get_revision('184_domestic_request_withdraw').down_revision == '182_announcement_reads'
    assert script.get_revision('183_portal_password_login').down_revision == '182_announcement_reads'


def test_full_main_from_deployed_portal_only_runs_pending_business_changes():
    script = ScriptDirectory(str(ROOT / 'backend/alembic'))
    actual = [step.revision.revision for step in script._upgrade_revs('head', '186_portal_announcement_merge')]
    assert actual == ['186_domestic_delivery', '192_wa_sync_fencing', '193_wa_ai_assistant',
                      '194_navigation_preferences', '195_main_portal_merge']
    reverse = [step.revision.revision for step in script._upgrade_revs('head', '194_navigation_preferences')]
    assert reverse == ['183_portal_password_login', '186_portal_announcement_merge', '195_main_portal_merge']
