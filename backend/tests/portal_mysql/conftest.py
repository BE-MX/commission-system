"""Opt-in owned MySQL process. Never accepts a database URL or shared server.

Run from backend with --confcutdir=tests/portal_mysql. The workspace MUST be new.
Only the supplied mysqld executable is used; no Windows service is installed.
"""
import json
from pathlib import Path
import secrets
import socket
import subprocess
import time

import pymysql
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL


BACKEND = Path(__file__).resolve().parents[2]
ALLOWED = {}
original_connect = pymysql.connect


def verify_connection(values):
    if not ALLOWED or values.get('host') != '127.0.0.1' or values.get('port') != ALLOWED['port']:
        raise AssertionError('Only this test-owned loopback MySQL process may be contacted')
    if values.get('database', values.get('db')) not in (None, ALLOWED['database']):
        raise AssertionError('Unexpected database')
    if values.get('password', values.get('passwd')) != ALLOWED['password']:
        raise AssertionError('Unexpected credentials')


def isolated_connect(*args, **kwargs):
    assert not args
    verify_connection(kwargs)
    return original_connect(**kwargs)


def isolated_engine(dialect, connection_record, args, kwargs):
    assert dialect.name == 'mysql', 'This suite requires real MySQL'
    verify_connection(kwargs)


@pytest.fixture(scope='session')
def mysql_connections_guard():
    # Collection/default skips must not change unrelated test connection behavior.
    previous = pymysql.connect
    pymysql.connect = isolated_connect
    event.listen(Engine, 'do_connect', isolated_engine)
    try:
        yield
    finally:
        event.remove(Engine, 'do_connect', isolated_engine)
        pymysql.connect = previous
        ALLOWED.clear()


def pytest_addoption(parser):
    group = parser.getgroup('portal-owned-mysql')
    group.addoption('--portal-full-chain', action='store_true', help='Standalone fresh database historical replay')
    for name in ('node', 'module', 'chromium'):
        group.addoption('--portal-browser-' + name, default=None, help='Opt-in browser runtime path')
    group.addoption('--portal-mode-node', default=None, help='Explicit local Node binary for mode privilege tests')
    group.addoption('--portal-mode-mysql2', default=None, help='Explicit local mysql2 promise.js for mode privilege tests')
    group.addoption('--portal-mysqld', default=None, help='Absolute path to a verified mysqld executable')
    group.addoption('--portal-mysql-workspace', default=None, help='New disposable directory, must not exist')


def pytest_collection_modifyitems(config, items):
    if config.getoption('portal_full_chain') and any(item.path.name != 'test_mysql_full_chain.py' for item in items):
        raise pytest.UsageError('--portal-full-chain requires selecting only test_mysql_full_chain.py')


@pytest.fixture(scope='session')
def mysql_engine(request):
    binary = request.config.getoption('portal_mysqld')
    workspace = request.config.getoption('portal_mysql_workspace')
    if not binary or not workspace:
        pytest.skip('Explicit --portal-mysqld and --portal-mysql-workspace required')
    assert not (BACKEND / '.env').exists(), 'Use a checkout without backend/.env'
    request.getfixturevalue('mysql_connections_guard')
    executable = Path(binary).resolve(strict=True)
    assert executable.name.lower() == 'mysqld.exe'
    directory = Path(workspace).resolve()
    assert directory.is_absolute() and directory.parent.is_dir() and not directory.exists()
    directory.mkdir()
    data = directory / 'data'
    temporary = directory / 'temp'; temporary.mkdir()
    password = secrets.token_urlsafe(36)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    ALLOWED.update(port=port, password=password, database='portal_isolated_test')
    base = [str(executable), '--no-defaults', '--basedir=' + executable.parent.parent.as_posix(),
        '--datadir=' + data.as_posix(), '--tmpdir=' + temporary.as_posix()]
    initialized = subprocess.run(base + ['--initialize-insecure', '--console'],
        capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    assert initialized.returncode == 0, initialized.stderr
    init = directory / 'bootstrap.sql'
    init.write_text("ALTER USER 'root'@'localhost' IDENTIFIED BY '" + password + "';\n", encoding='utf-8')
    server = subprocess.Popen(base + ['--bind-address=127.0.0.1', f'--port={port}', '--mysqlx=OFF',
        '--skip-log-bin', '--performance-schema=ON', '--init-file=' + init.as_posix(),
        '--log-error=' + (directory / 'mysql.log').as_posix(), '--pid-file=' + (directory / 'mysql.pid').as_posix()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    engine = None
    connect = dict(host='127.0.0.1', port=port, user='root', password=password, connect_timeout=1, autocommit=True)
    try:
        connection = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            assert server.poll() is None, 'Owned mysqld exited; inspect the local mysql.log'
            try:
                connection = pymysql.connect(**connect)
                break
            except pymysql.err.OperationalError as error:
                if error.args[0] not in (2003, 1045): raise
                time.sleep(.1)
        assert connection is not None, 'Owned MySQL did not become ready in 45 seconds'
        with connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT @@datadir, @@port, @@bind_address, VERSION(), @@server_uuid')
                actual_dir, actual_port, address, version, server_uuid = cursor.fetchone()
                assert Path(actual_dir).resolve() == data.resolve() and actual_port == port
                assert address == '127.0.0.1' and version.startswith(('8.0.', '8.4.'))
                cursor.execute('CREATE DATABASE portal_isolated_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        init.unlink()
        engine = create_engine(URL.create('mysql+pymysql', username='root', password=password,
            host='127.0.0.1', port=port, database=ALLOWED['database']),
            isolation_level='REPEATABLE READ', pool_size=5, max_overflow=0, hide_parameters=True)
        @event.listens_for(engine, 'connect')
        def configure(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
                cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        (directory / 'runtime.json').write_text(json.dumps({'version': version, 'port': port,
            'server_uuid': server_uuid, 'datadir': str(data), 'scope': 'isolated local process'}, indent=2), encoding='utf-8')
        yield engine
    finally:
        if engine is not None: engine.dispose()
        if server.poll() is None:
            try:
                with pymysql.connect(**connect) as connection:
                    with connection.cursor() as cursor: cursor.execute('SHUTDOWN')
            except pymysql.err.Error as error:
                print('Test server shutdown request failed: MySQL error', error.args[0], flush=True)
            try: server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.terminate(); server.wait(timeout=10)
        if init.exists(): init.unlink()
        ALLOWED.clear()
        assert server.poll() is not None


from mysql_schema import migrated  # noqa: E402,F401; one suite-wide migration fixture

from mysql_service_fixture import service_schema, trade  # noqa: E402,F401

from mysql_editor_fixture import editor  # noqa: E402,F401; shared real employee HTTP fixture
