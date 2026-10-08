"""Actual Node/mysql2 and owned MySQL privilege boundary; no supplier entry point."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect,text

MODE='outbound-worker-v1'
TABLE='ark_order_portal_auth_barriers'
SAFE_ERROR='Outbound protocol mode cannot be confirmed'
PARENT='171_customer_tag_display_value'


@pytest.fixture
def node_runtime(request):
    node=request.config.getoption('portal_mode_node')
    driver=request.config.getoption('portal_mode_mysql2')
    if not node or not driver:
        pytest.skip('Explicit --portal-mode-node and --portal-mode-mysql2 are required')
    binary=Path(node).resolve(strict=True);module=Path(driver).resolve(strict=True)
    assert binary.name.lower()=='node.exe' and module.name=='promise.js'
    package=json.loads((module.parent/'package.json').read_text(encoding='utf-8'))
    assert package['name']=='mysql2'
    return binary,module


@pytest.fixture
def target(node_runtime,migrated):
    from app.invoice.models import OkkiOutboundTask
    # Use the actual existing queue definition as an additional grant anchor.
    OkkiOutboundTask.__table__.create(migrated,checkfirst=True)
    with migrated.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code LIKE 'outbound-worker-%'"))
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('DELETE FROM alembic_version'))
        connection.execute(text('INSERT INTO alembic_version(version_num) VALUES (:revision)'),{'revision':'176_portal_pi_header'})
        uuid=connection.scalar(text('SELECT @@server_uuid'))
    def probe(user='root'):
        node,driver=node_runtime
        root=Path(__file__).resolve().parents[3]
        config={'connection':{'host':'127.0.0.1','port':migrated.url.port,'user':user,
                             'password':migrated.url.password,'database':migrated.url.database},
                'server_uuid':uuid,'module':str(root/'deploy/okki_outbound_mode.mjs')}
        result=subprocess.run([str(node),str(Path(__file__).with_name('node_mode_probe.mjs')),str(driver)],
            input=json.dumps(config),text=True,capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        # Never include the credential-bearing input or raw driver output in assertions.
        assert result.returncode==0,'Owned Node process failed; driver output intentionally hidden'
        try:return json.loads(result.stdout)
        except ValueError:pytest.fail('Owned Node mode result is not canonical JSON')
    def rows():
        with migrated.connect() as connection:
            return {name:list(connection.execute(text('SELECT * FROM `'+name+'`')).tuples())
                    for name in inspect(connection).get_table_names()}
    yield SimpleNamespace(engine=migrated,probe=probe,rows=rows)
    with migrated.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code LIKE 'outbound-worker-%'"))
        connection.execute(text('DELETE FROM alembic_version'))


@pytest.mark.parametrize('installed',[True,False])
def test_hidden_mode_table_never_grants_legacy_to_actual_low_privilege_node(target,installed):
    username='owned_node_mode_reader'
    with target.engine.begin() as connection:
        if installed:
            connection.execute(text(f'INSERT INTO {TABLE}(code,version) VALUES (:code,1)'),{'code':MODE})
        connection.execute(text("CREATE USER 'owned_node_mode_reader'@'%' IDENTIFIED BY :password"),
                           {'password':target.engine.url.password})
        for table in ('ark_invoices','ark_okki_outbound_tasks'):
            connection.execute(text(f"GRANT SELECT,UPDATE ON portal_isolated_test.{table} TO 'owned_node_mode_reader'@'%'") )
    try:
        before=target.rows();result=target.probe(username)
        assert result['metadata_count']==0
        assert target.rows()==before
        assert 'password' not in json.dumps(result) and username not in json.dumps(result)
        assert (result['mode'],result['mode_error'],result['legacy_allowed'],result['gate_error']) == (
            None,SAFE_ERROR,False,SAFE_ERROR)
    finally:
        with target.engine.begin() as connection:
            connection.execute(text("DROP USER 'owned_node_mode_reader'@'%'") )


@pytest.mark.parametrize('installed',[True,False])
def test_actual_privileged_node_reads_known_mode_or_initial_empty_table(target,installed):
    if installed:
        with target.engine.begin() as connection:
            connection.execute(text(f'INSERT INTO {TABLE}(code,version) VALUES (:code,1)'),{'code':MODE})
    before=target.rows();result=target.probe()
    assert result['metadata_count']==1
    assert result['mode']==(MODE if installed else 'legacy') and result['mode_error'] is None
    assert result['legacy_allowed'] is (not installed)
    assert result['gate_error']==('Enabled outbound worker owns execution; legacy creation is prohibited' if installed else None)
    assert target.rows()==before


@pytest.mark.parametrize('revision',[PARENT,'175_customer_order_portal','176_portal_pi_header','999_unknown'])
def test_missing_mode_table_requires_exact_trusted_preportal_head(target,revision):
    with target.engine.begin() as connection:
        connection.execute(text('UPDATE alembic_version SET version_num=:revision'),{'revision':revision})
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_mode_table_backup'))
    try:
        before=target.rows();result=target.probe()
        assert result['metadata_count']==0
        if revision==PARENT:
            assert result['mode']=='legacy' and result['legacy_allowed'] and result['mode_error'] is None
        else:
            assert result['mode'] is None and result['mode_error']==SAFE_ERROR and not result['legacy_allowed']
        assert target.rows()==before
    finally:
        with target.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_mode_table_backup TO {TABLE}'))


@pytest.mark.parametrize('rows',[
    [("outbound-worker-v2",1)],[(MODE,2)],[(MODE,1),("outbound-worker-v2",1)],
])
def test_actual_readable_unknown_modes_never_permit_legacy(target,rows):
    with target.engine.begin() as connection:
        for code,version in rows:
            connection.execute(text(f'INSERT INTO {TABLE}(code,version) VALUES (:code,:version)'),
                               {'code':code,'version':version})
    before=target.rows();result=target.probe()
    assert (result['mode'],result['mode_error'],result['legacy_allowed'],result['gate_error']) == (
        None,SAFE_ERROR,False,SAFE_ERROR)
    assert target.rows()==before


@pytest.mark.parametrize('head_state',['empty','multiple','missing'])
def test_actual_missing_mode_table_with_unconfirmed_head_is_rejected(target,head_state):
    with target.engine.begin() as connection:
        connection.execute(text('DELETE FROM alembic_version'))
        if head_state=='multiple':
            for revision in (PARENT,'176_portal_pi_header'):
                connection.execute(text('INSERT INTO alembic_version VALUES (:revision)'),{'revision':revision})
        if head_state=='missing':
            connection.execute(text('RENAME TABLE alembic_version TO owned_head_backup'))
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_mode_table_backup'))
    try:
        before=target.rows();result=target.probe()
        assert (result['mode'],result['mode_error'],result['legacy_allowed'],result['gate_error']) == (
            None,SAFE_ERROR,False,SAFE_ERROR)
        assert target.rows()==before
    finally:
        with target.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_mode_table_backup TO {TABLE}'))
            if head_state=='missing':
                connection.execute(text('RENAME TABLE owned_head_backup TO alembic_version'))


def test_actual_missing_mode_table_cannot_use_unreadable_schema_head(target):
    username='owned_node_head_reader'
    with target.engine.begin() as connection:
        connection.execute(text("CREATE USER 'owned_node_head_reader'@'%' IDENTIFIED BY :password"),
                           {'password':target.engine.url.password})
        connection.execute(text(f"GRANT SELECT ON portal_isolated_test.{TABLE} TO 'owned_node_head_reader'@'%'") )
        connection.execute(text('UPDATE alembic_version SET version_num=:revision'),{'revision':PARENT})
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_mode_table_backup'))
    try:
        # Verify that this actual user reaches missing-table compatibility but cannot read the head.
        engine=target.engine.execution_options(isolation_level='AUTOCOMMIT')
        import pymysql
        with pymysql.connect(host='127.0.0.1',port=engine.url.port,user=username,
                            password=engine.url.password,database=engine.url.database) as connection:
            with connection.cursor() as cursor:
                with pytest.raises(pymysql.err.ProgrammingError) as missing:
                    cursor.execute(f'SELECT code,version FROM {TABLE}')
                assert missing.value.args[0]==1146
                with pytest.raises(pymysql.err.OperationalError) as denied:
                    cursor.execute('SELECT version_num FROM alembic_version')
                assert denied.value.args[0]==1142
        before=target.rows();result=target.probe(username)
        assert (result['mode'],result['mode_error'],result['legacy_allowed'],result['gate_error']) == (
            None,SAFE_ERROR,False,SAFE_ERROR)
        assert target.rows()==before
    finally:
        with target.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_mode_table_backup TO {TABLE}'))
            connection.execute(text("DROP USER 'owned_node_head_reader'@'%'") )
