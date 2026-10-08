"""Actual Python mode reader: missing/unreadable is not evidence of legacy."""
import pytest
from sqlalchemy import inspect,text,create_engine,event
from sqlalchemy.orm import sessionmaker
from test_mysql_outbound_mode import boot,install_record,MODE,TABLE  # noqa: F401


@pytest.mark.parametrize('heads',[
    [],['176_portal_pi_header'],['unknown_future'],
    ['171_customer_tag_display_value','176_portal_pi_header']])
def test_missing_mode_table_with_unconfirmed_head_never_enables_legacy(boot,heads):
    boot.settings.PORTAL_ENABLED=False
    with boot.engine.begin() as connection:
        created=not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        for head in heads:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_python_mode_backup'))
    try:
        with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
            boot.initialize()
    finally:
        with boot.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_python_mode_backup TO {TABLE}'))
            if created:connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})


@pytest.mark.parametrize('installed',[False,True])
def test_actual_low_privilege_off_bootstrap_cannot_use_hidden_mode_as_legacy(boot,installed):
    if installed:install_record(boot)
    boot.settings.PORTAL_ENABLED=False
    with boot.engine.begin() as connection:
        connection.execute(text("CREATE USER 'owned_python_mode_reader'@'%' IDENTIFIED BY :password"),
                           {'password':boot.engine.url.password})
        connection.execute(text("GRANT SELECT,UPDATE ON portal_isolated_test.ark_invoices TO 'owned_python_mode_reader'@'%'") )
    low=create_engine(boot.engine.url.set(username='owned_python_mode_reader'),hide_parameters=True)
    try:
        before=boot.snapshot()
        with low.connect() as connection:
            count=connection.scalar(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:name"),{'name':TABLE})
            assert count==0
        boot.factory_state['current']=sessionmaker(bind=low)
        with pytest.raises(RuntimeError,match='bootstrap is unavailable') as rejected:
            boot.initialize()
        assert 'owned_python_mode_reader' not in str(rejected.value)
        assert boot.snapshot()==before
    finally:
        boot.factory_state['current']=boot.factory
        low.dispose()
        with boot.engine.begin() as connection:
            connection.execute(text("DROP USER 'owned_python_mode_reader'@'%'") )


@pytest.mark.parametrize('mapper_head,default_head,allowed',[
    ('176_portal_pi_header','171_customer_tag_display_value',False),
    ('171_customer_tag_display_value','176_portal_pi_header',True)])
def test_mode_and_parent_evidence_use_actual_mapper_connection(boot,mapper_head,default_head,allowed):
    from app.portal.models import AuthorityBarrier
    from app.invoice.outbound_mode import initialize
    with boot.engine.begin() as connection:
        created=not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':default_head})
        connection.execute(text('CREATE DATABASE portal_owned_mode_bind'))
        connection.execute(text('CREATE TABLE portal_owned_mode_bind.alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('INSERT INTO portal_owned_mode_bind.alembic_version VALUES (:head)'),{'head':mapper_head})
    # Connect first to the allowed owned target, then use the second owned schema.
    alternate=create_engine(boot.engine.url,hide_parameters=True);seen=[]
    @event.listens_for(alternate,'connect')
    def use_owned(connection,record):
        with connection.cursor() as cursor:cursor.execute('USE portal_owned_mode_bind')
    @event.listens_for(alternate,'before_cursor_execute')
    def observe_target(connection,cursor,statement,parameters,context,executemany):
        if 'ark_order_portal_auth_barriers' in statement or 'SELECT version_num' in statement:
            cursor.execute('SELECT DATABASE(), CONNECTION_ID()')
            database,connection_id=cursor.fetchone()
            seen.append(('head' if 'SELECT version_num' in statement else 'mode',database,connection_id))
    factory=sessionmaker(bind=boot.engine,binds={AuthorityBarrier:alternate})
    try:
        before=boot.snapshot()
        if allowed:assert initialize(factory,portal_enabled=False)=='legacy'
        else:
            with pytest.raises(RuntimeError,match='mode cannot be confirmed'):
                initialize(factory,portal_enabled=False)
        assert [(phase,database) for phase,database,_ in seen]==[('mode','portal_owned_mode_bind'),('head','portal_owned_mode_bind')]
        assert type(seen[0][2]) is int and seen[0][2]==seen[1][2]
        assert boot.snapshot()==before
    finally:
        alternate.dispose()
        with boot.engine.begin() as connection:
            connection.execute(text('DROP DATABASE portal_owned_mode_bind'))
            if created:connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})


def test_missing_both_mode_and_parent_table_refuses_initial_off(boot):
    boot.settings.PORTAL_ENABLED=False
    with boot.engine.begin() as connection:
        head_present=inspect(connection).has_table('alembic_version')
        if head_present:connection.execute(text('RENAME TABLE alembic_version TO owned_parent_backup'))
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_python_mode_backup'))
    try:
        with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
            boot.initialize()
    finally:
        with boot.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_python_mode_backup TO {TABLE}'))
            if head_present:connection.execute(text('RENAME TABLE owned_parent_backup TO alembic_version'))
