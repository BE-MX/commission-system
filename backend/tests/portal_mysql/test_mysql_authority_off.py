"""Installed authority persists OFF; exact parent is synthetic boundary evidence."""
from contextlib import contextmanager
from copy import copy
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.portal import authority
from app.portal.errors import PortalError
from app.portal.models import AuthorityBarrier, CustomerAccess, PortalSession, Quote, Invitation, Membership
from app.core.time import beijing_now
from app.customer.models import CustomerExternalIdentity
from test_mysql_receipt_authority import receipt_app, assembled, boot, login, change_user  # noqa: F401

TABLE='ark_order_portal_auth_barriers'
PARENT='171_customer_tag_display_value'


@contextmanager
def missing_protocol(engine,heads):
    with engine.begin() as connection:
        created=not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        for head in heads:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_authority_backup'))
    try:yield
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_authority_backup TO {TABLE}'))
            if created:connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})


@pytest.fixture
def off_schema(migrated,monkeypatch):
    settings=SimpleNamespace(PORTAL_ENABLED=False,PORTAL_LOCK_WAIT_SECONDS=2)
    monkeypatch.setattr(authority,'get_settings',lambda:settings)
    return migrated,settings


@pytest.mark.parametrize('heads,enabled,force,allowed',[
    ([PARENT],False,False,True),([],False,False,False),
    (['176_customer_order_portal'],False,False,False),
    (['177_portal_pi_header'],False,False,False),(['unknown_future'],False,False,False),
    ([PARENT,'177_portal_pi_header'],False,False,False),
    ([PARENT],True,False,False),([PARENT],False,True,False),
])
def test_only_exact_missing_parent_allows_legacy_without_committing_caller(off_schema,heads,enabled,force,allowed):
    engine,settings=off_schema;settings.PORTAL_ENABLED=enabled
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS owned_authority_caller(id INT PRIMARY KEY, value INT)'))
        connection.execute(text('INSERT INTO owned_authority_caller VALUES(1,0) ON DUPLICATE KEY UPDATE value=0'))
    with missing_protocol(engine,heads):
        with Session(engine) as db:
            db.execute(text('UPDATE owned_authority_caller SET value=1 WHERE id=1'))
            if allowed:
                assert authority.lock_authority(db,force=force) is None
                authority.suspend_customer_access(db,[1]);authority.review_customer_bindings(db,[1])
            else:
                with pytest.raises(PortalError) as rejected:authority.lock_authority(db,force=force)
                assert rejected.value.status==503
            assert db.in_transaction()
            with engine.connect() as observer:
                assert observer.scalar(text('SELECT value FROM owned_authority_caller WHERE id=1'))==0
            assert db.scalar(text('SELECT value FROM owned_authority_caller WHERE id=1'))==1
            db.rollback()
        with engine.connect() as observer:
            assert observer.scalar(text('SELECT value FROM owned_authority_caller WHERE id=1'))==0


def test_installed_empty_worker_mode_off_still_locks_and_versions_authority(off_schema):
    engine,_=off_schema
    with engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code LIKE 'outbound-worker-%'"))
    with Session(engine) as db:
        row=authority.lock_authority(db);assert row is not None
        version=row.version
        assert authority.lock_authority(db) is row
        authority.authority_changed(db);db.flush()
        assert row.version==version+1
        db.rollback()
    with Session(engine) as db:assert db.get(AuthorityBarrier,'authority').version==version


def test_installed_table_without_authority_is_not_legacy(off_schema):
    engine,_=off_schema
    with engine.begin() as connection:
        original=connection.scalar(text(f"SELECT version FROM {TABLE} WHERE code='authority'"))
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code='authority'"))
    try:
        with Session(engine) as db:
            with pytest.raises(PortalError) as rejected:authority.lock_authority(db)
            assert rejected.value.status==503
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"INSERT INTO {TABLE}(code,version) VALUES ('authority',:version)"),{'version':original})


@pytest.mark.parametrize('mapper_head,default_head,allowed',[
    (PARENT,'177_portal_pi_header',True),('177_portal_pi_header',PARENT,False)])
def test_parent_and_timeout_share_actual_authority_mapper_connection(off_schema,mapper_head,default_head,allowed):
    engine,_=off_schema;seen=[];alternate=None
    with engine.begin() as connection:
        created=not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':default_head})
        connection.execute(text('CREATE DATABASE portal_owned_authority_bind'))
        connection.execute(text('CREATE TABLE portal_owned_authority_bind.alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('INSERT INTO portal_owned_authority_bind.alembic_version VALUES (:head)'),{'head':mapper_head})
    alternate=create_engine(engine.url,hide_parameters=True)
    @event.listens_for(alternate,'connect')
    def use_owned(connection,record):
        with connection.cursor() as cursor:cursor.execute('USE portal_owned_authority_bind')
    def observe(connection,cursor,statement,parameters,context,executemany):
        if TABLE in statement or 'version_num FROM' in statement or 'innodb_lock_wait_timeout' in statement:
            cursor.execute('SELECT DATABASE(),CONNECTION_ID()')
            schema,connection_id=cursor.fetchone();seen.append((statement,schema,connection_id))
    event.listen(alternate,'before_cursor_execute',observe);event.listen(engine,'before_cursor_execute',observe)
    try:
        factory=sessionmaker(bind=engine,binds={AuthorityBarrier:alternate})
        with factory() as db:
            if allowed:assert authority.lock_authority(db) is None
            else:
                with pytest.raises(PortalError):authority.lock_authority(db)
            captured=list(seen);db.rollback()
        assert len(captured)==4,captured
        assert all(schema=='portal_owned_authority_bind' for _,schema,_ in captured)
        assert len({identifier for _,_,identifier in captured})==1
        assert 'innodb_lock_wait_timeout' in captured[0][0] and 'SET SESSION' in captured[1][0]
        assert TABLE in captured[2][0] and 'FOR UPDATE' in captured[2][0]
        assert 'version_num FROM' in captured[3][0]
    finally:
        event.remove(alternate,'before_cursor_execute',observe);event.remove(engine,'before_cursor_execute',observe)
        alternate.dispose()
        with engine.begin() as connection:
            connection.execute(text('DROP DATABASE portal_owned_authority_bind'))
            if created:connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})


def test_hidden_installed_authority_never_becomes_legacy(off_schema):
    engine,_=off_schema
    with engine.begin() as connection:
        connection.execute(text("CREATE USER 'owned_authority_hidden'@'%' IDENTIFIED BY :password"),{'password':engine.url.password})
        connection.execute(text("GRANT SELECT ON portal_isolated_test.ark_invoices TO 'owned_authority_hidden'@'%'"))
    low=create_engine(engine.url.set(username='owned_authority_hidden'),hide_parameters=True);denied=[]
    @event.listens_for(low,'handle_error')
    def observe_denial(context):
        denied.append(context.original_exception.args[0])
    try:
        with Session(low) as db:
            with pytest.raises(PortalError) as rejected:authority.lock_authority(db)
            assert rejected.value.status==503
            assert denied==[1142]
    finally:
        low.dispose()
        with engine.begin() as connection:connection.execute(text("DROP USER 'owned_authority_hidden'@'%'"))


@pytest.mark.parametrize('method',['suspend','review'])
def test_customer_invalidation_still_occurs_off_and_does_not_revive_on(trade,monkeypatch,method):
    ctx=trade;settings=copy(authority.get_settings());settings.PORTAL_ENABLED=False
    monkeypatch.setattr(authority,'get_settings',lambda:settings)
    with Session(ctx.engine) as db:
        authority.lock_authority(db)
        access=db.get(CustomerAccess,ctx.access_id);customer_id=access.customer_id
        original_version=access.auth_version
        member=db.scalar(select(Membership).where(Membership.access_id==access.id))
        invitation=Invitation(site_id=access.site_id,account_id=ctx.account_id,access_id=access.id,
            membership_id=member.id,token_hash=uuid4().hex+uuid4().hex,account_version=ctx.account_version,
            access_version=access.auth_version,membership_version=member.version,
            expires_at=beijing_now()+timedelta(hours=1),created_by=ctx.actor)
        db.add(invitation);db.flush();invitation_id=invitation.id
        if method=='review':
            identity=db.get(CustomerExternalIdentity,access.external_identity_id)
            identity.status='review_required';db.flush()
            authority.review_customer_bindings(db,[customer_id])
        else:authority.suspend_customer_access(db,[customer_id])
        db.commit()
    settings.PORTAL_ENABLED=True
    with Session(ctx.engine) as db:
        access=db.get(CustomerAccess,ctx.access_id)
        assert access.status=='review_required' and access.auth_version==original_version+1
        assert db.get(PortalSession,ctx.session_id).revoked_at is not None
        assert db.get(Invitation,invitation_id).revoked_at is not None
        assert db.scalar(select(Quote).where(Quote.public_id==str(ctx.body.quote_id))).status=='expired'


def test_verified_parent_keeps_actual_employee_update_positive(receipt_app,monkeypatch):
    c=receipt_app;c.app.settings.PORTAL_ENABLED=False
    monkeypatch.setattr(authority,'get_settings',lambda:c.app.settings)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        # Running actual application; not a pre-172 whole-startup claim.
        with missing_protocol(c.ctx.engine,[PARENT]):
            change_user(client,c,root,{'is_active':False})
            from app.auth.models import ArkUser
            with Session(c.ctx.engine) as db:assert not db.get(ArkUser,c.ctx.actor).is_active
            change_user(client,c,root,{'is_active':True})


def test_stale_parent_snapshot_does_not_authorize_legacy(off_schema):
    engine,_=off_schema
    with missing_protocol(engine,[PARENT]):
        with Session(engine) as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version'))==PARENT
            with engine.begin() as newer:
                newer.execute(text("UPDATE alembic_version SET version_num='177_portal_pi_header'"))
            # RR still sees the old parent before the helper's current lock read.
            assert db.scalar(text('SELECT version_num FROM alembic_version'))==PARENT
            with pytest.raises(PortalError) as rejected:authority.lock_authority(db)
            assert rejected.value.status==503
            assert db.in_transaction();db.rollback()


@pytest.mark.parametrize('stage',['timeout_read','timeout_set'])
def test_timeout_initialization_failure_cannot_become_legacy(off_schema,stage):
    engine,_=off_schema;seen=[]
    def fail(connection,cursor,statement,parameters,context,executemany):
        prefix='SELECT @@SESSION' if stage=='timeout_read' else 'SET SESSION'
        if not seen and statement.startswith(prefix):
            seen.append(stage)
            # Deliberate 1146 on timeout initialization is not missing barrier.
            raise OperationalError('owned-timeout-failure',{},Exception(1146,'owned-unavailable'))
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with Session(engine) as db:
            with pytest.raises(PortalError) as rejected:authority.lock_authority(db)
            assert rejected.value.status==503
            assert seen==[stage];db.rollback()
    finally:event.remove(engine,'before_cursor_execute',fail)


@pytest.mark.parametrize('method',['suspend','review'])
def test_helpers_off_reject_missing_first_lock_and_expired_legacy_capability(off_schema,method):
    engine,_=off_schema
    helper=authority.suspend_customer_access if method=='suspend' else authority.review_customer_bindings
    with Session(engine) as db:
        with pytest.raises(RuntimeError):helper(db,[1])
    with missing_protocol(engine,[PARENT]):
        with Session(engine) as db:
            assert authority.lock_authority(db) is None
            db.commit()
            with pytest.raises(RuntimeError):helper(db,[1])
            assert authority.lock_authority(db) is None
            with pytest.raises(PortalError):authority.lock_authority(db,force=True)
            with pytest.raises(RuntimeError):helper(db,[1])


def test_connection_denial_is_safe_unavailable_not_legacy(off_schema):
    engine,_=off_schema
    with engine.begin() as connection:
        connection.execute(text("CREATE USER 'owned_authority_connect'@'%' IDENTIFIED BY :password"),{'password':engine.url.password})
    low=create_engine(engine.url.set(username='owned_authority_connect'),hide_parameters=True)
    try:
        with Session(low) as db:
            with pytest.raises(PortalError) as rejected:authority.lock_authority(db)
            assert rejected.value.status==503
    finally:
        low.dispose()
        with engine.begin() as connection:connection.execute(text("DROP USER 'owned_authority_connect'@'%'"))
