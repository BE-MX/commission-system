"""Both preflight paths must report every migration Alembic will execute, without a DB."""
import ast
from pathlib import Path
import sys

import pytest
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


@pytest.mark.parametrize('current_revision', ['150_domestic_item_guest', '146_expo_beautify_prompt', '145_domestic_order_guest', '152_shipping_media_recall'])
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
    if current_revision == '150_domestic_item_guest':
        assert pending[:2] == ['146_expo_beautify_prompt', '152_shipping_media_recall']
        assert pending[-1] == head
