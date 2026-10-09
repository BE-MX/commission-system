"""Deployment bounds cannot silently disable portal row-lock timeout."""
import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_lock_wait_default_is_bounded():
    assert Settings(_env_file=None).PORTAL_LOCK_WAIT_SECONDS == 5


@pytest.mark.parametrize('seconds',[0,-1,31])
def test_invalid_lock_wait_setting_is_rejected(seconds):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, PORTAL_LOCK_WAIT_SECONDS=seconds)


@pytest.mark.parametrize('seconds',[1,30])
def test_lock_wait_boundaries_are_accepted(seconds):
    assert Settings(_env_file=None, PORTAL_LOCK_WAIT_SECONDS=seconds).PORTAL_LOCK_WAIT_SECONDS == seconds


def test_main_registers_only_specific_upstream_busy_exception():
    import ast
    from pathlib import Path
    from fastapi import FastAPI
    from app.portal.errors import PortalError, TransactionBusy, register_portal_error_handler
    app=FastAPI(); register_portal_error_handler(app)
    assert TransactionBusy in app.exception_handlers and PortalError not in app.exception_handlers
    source=Path(__file__).resolve().parents[2]/'app/main.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    assert any(isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
        and isinstance(node.value.func,ast.Name) and node.value.func.id=='register_portal_error_handler'
        and len(node.value.args)==1 and isinstance(node.value.args[0],ast.Name)
        and node.value.args[0].id=='app' for node in tree.body)
