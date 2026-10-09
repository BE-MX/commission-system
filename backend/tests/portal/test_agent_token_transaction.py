from types import SimpleNamespace

import pytest
from sqlalchemy import event

from test_upstream_authority import upstream_db, authorization_db, binding_db
from app.auth.models import ArkPermission
from app.auth.utils import hash_token
from app.mcp.auth import resolve_token
from app.mcp.models import MCPToken
from app.sales_automation.dependencies import require_sales_agent_for_identity_write


@pytest.fixture
def token_db(upstream_db):
    db = upstream_db
    MCPToken.__table__.create(db.get_bind())
    db.get(ArkPermission, 1).code = "sales_automation:invoke"
    db.add(MCPToken(id=1, token_hash=hash_token("isolated-test-token"), user_id=1, is_active=True))
    db.commit()
    return db


def test_candidate_auth_keeps_transaction_and_rolls_back_usage(token_db):
    db = token_db
    commits = []
    event.listen(db, "after_commit", lambda session: commits.append(True))
    identity = require_sales_agent_for_identity_write(SimpleNamespace(credentials="isolated-test-token"), db)
    assert identity["sub"] == "1" and not commits
    assert db.get_transaction() is db.info["portal_authority_scope"][0]
    db.flush()
    assert db.get(MCPToken, 1).last_used_at is not None
    db.rollback()
    assert db.get(MCPToken, 1).last_used_at is None


def test_other_token_callers_keep_existing_usage_commit(token_db):
    db = token_db
    commits = []
    event.listen(db, "after_commit", lambda session: commits.append(True))
    assert resolve_token(db, "isolated-test-token")["sub"] == "1"
    assert commits == [True]
    db.rollback()
    assert db.get(MCPToken, 1).last_used_at is not None
