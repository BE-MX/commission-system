"""Reject mixed routing/release scopes before any deployment dispatch."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('other,value', [('office_lan_https', 'missing-plan.json'),
                                       ('receipt_routing_only', True),
                                       ('revision', 'a' * 40)])
def test_whatsapp_mixed_scope_rejected_before_dispatch(other, value):
    source = Path(__file__).resolve().parents[1] / 'publish.py'
    tree = ast.parse(source.read_text(encoding='utf8'))
    main = next(node for node in tree.body if isinstance(node, ast.If)
                and ast.unparse(node.test) == "__name__ == '__main__'")
    guarded = next(node for node in main.body if isinstance(node, ast.Try))
    # Execute the real CLI pre-dispatch statements only; no deployment imports,
    # subprocesses, network requests or application actions can run in this test.
    statements = []
    for node in guarded.body:
        if isinstance(node, ast.If) and ast.unparse(node.test) == 'args.sales_agent_stage':
            break
        statements.append(node)
    args = SimpleNamespace(whatsapp_routing_only=True, prepare_only=True,
                           sales_agent_model_config=None, sales_agent_runtime_revision=None,
                           sales_agent_reuse_model=False, sales_agent_stage=None)
    setattr(args, other, value)
    parser = SimpleNamespace(parse_args=lambda: args)
    with pytest.raises(RuntimeError, match='WhatsApp routing only accepts'):
        exec(compile(ast.Module(body=statements, type_ignores=[]), str(source), 'exec'),
             {'parser': parser})
