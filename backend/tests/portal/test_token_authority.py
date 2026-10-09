"""Token administration must serialize with identity-writing Agent requests."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import Integer, MetaData, event, func, select
from test_upstream_authority import upstream_db, authorization_db, binding_db
from app.auth.models import ArkUser, ArkPermission
from app.auth.utils import hash_token
from app.mcp import token_admin
from app.mcp.auth import MCPAuthError, resolve_token
from app.mcp.models import MCPToken
from app.portal.models import AuthorityBarrier
from app.sales_automation.dependencies import require_sales_agent_for_identity_write


ACTOR = {'sub': '1', 'roles': ['super_admin'], 'permissions': ['mcp:admin']}


@pytest.fixture
def token_admin_db(upstream_db):
    db = upstream_db
    metadata = MetaData()
    ArkUser.__table__.to_metadata(metadata)
    table = MCPToken.__table__.to_metadata(metadata)
    table.c.id.type = Integer()  # SQLite needs INTEGER PK for its local autoincrement.
    table.create(db.get_bind())
    db.add(MCPToken(id=1, token_hash=hash_token('isolated-agent-token'), user_id=1, is_active=True, label='Identity worker'))
    db.commit()
    return db


def invoke(name, db):
    if name == 'issue':
        return token_admin.issue_token(token_admin.IssueTokenRequest(user_id=1, label='Identity worker'), db, ACTOR)
    return getattr(token_admin, name + '_token')(1, db, ACTOR)


@pytest.mark.parametrize('name', ['issue', 'rotate', 'revoke'])
def test_stale_admin_claim_rejected_before_token_lookup(token_admin_db, name):
    db = token_admin_db
    statements = []
    def capture(connection, cursor, sql, params, context, many): statements.append(sql)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        with pytest.raises(HTTPException) as caught: invoke(name, db)
        assert caught.value.status_code == 403
        assert AuthorityBarrier.__tablename__ in statements[0]
        assert not any('ark_mcp_tokens' in sql for sql in statements)
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
        db.rollback()
    assert db.get(MCPToken, 1).is_active


@pytest.mark.parametrize('name', ['issue', 'rotate', 'revoke'])
def test_live_admin_change_commits_with_authority(token_admin_db, name):
    db = token_admin_db
    db.get(ArkPermission, 1).code = 'mcp:admin'; db.commit()
    before = db.scalar(select(AuthorityBarrier.version)); db.commit()
    statements = []
    def capture(connection, cursor, sql, params, context, many): statements.append(sql)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try: result = invoke(name, db)
    finally: event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert result['code'] == 200
    assert AuthorityBarrier.__tablename__ in statements[0]
    assert db.scalar(select(AuthorityBarrier.version)) == before + 1
    if name in {'rotate', 'revoke'}:
        assert db.get(MCPToken, 1).is_active is False
        with pytest.raises(MCPAuthError): resolve_token(db, 'isolated-agent-token', commit_usage=False)
    if name in {'issue', 'rotate'}:
        assert result['data']['token']
        assert db.scalar(select(func.count()).select_from(MCPToken)) == 2


def test_rotation_failure_rolls_back_new_token_and_revocation(token_admin_db, monkeypatch):
    db = token_admin_db
    db.get(ArkPermission, 1).code = 'mcp:admin'; db.commit()
    before = db.scalar(select(AuthorityBarrier.version)); db.commit()
    def failed(): raise RuntimeError('Injected commit failure')
    monkeypatch.setattr(db, 'commit', failed)
    with pytest.raises(RuntimeError): token_admin.rotate_token(1, db, ACTOR)
    db.rollback()
    assert db.get(MCPToken, 1).is_active
    assert db.scalar(select(func.count()).select_from(MCPToken)) == 1
    assert db.scalar(select(AuthorityBarrier.version)) == before


def test_revoked_token_cannot_start_identity_write(token_admin_db):
    db = token_admin_db
    db.get(ArkPermission, 1).code = 'mcp:admin'; db.commit()
    token_admin.revoke_token(1, db, ACTOR)
    with pytest.raises(HTTPException) as caught:
        require_sales_agent_for_identity_write(SimpleNamespace(credentials='isolated-agent-token'), db)
    assert caught.value.status_code == 401
