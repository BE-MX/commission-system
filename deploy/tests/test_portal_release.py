"""Optional portal release construction; all effects use local fixtures."""
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish


@pytest.fixture
def builder(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, 'ROOT', tmp_path)
    monkeypatch.setattr(publish, 'STATE', tmp_path / '.deploy_state')
    publish.STATE.mkdir()
    for name in ('extensions/whatsapp-translation', 'frontend', 'frontend-pm', 'frontend-portal'):
        (tmp_path / name).mkdir(parents=True)
    portal = tmp_path / 'frontend-portal'
    (portal / 'package.json').write_text('{}')
    (portal / 'pnpm-lock.yaml').write_text('lockfileVersion: 9.0')
    (portal / 'source.js').write_text('first')
    monkeypatch.setattr(publish, 'npm_install', Mock())
    monkeypatch.setattr(publish, 'npm_command', lambda: 'mock-npm')
    monkeypatch.setattr(publish, 'pnpm_command', lambda: 'mock-pnpm')
    def run(args, cwd=None, capture=False):
        if '--version' in args: return 'test-runtime'
        if 'install' in args:
            (cwd / 'node_modules').mkdir(exist_ok=True)
            return ''
        output = Path(args[-1]); output.mkdir(parents=True, exist_ok=True)
        (output / ('latest.json' if 'package' in args else 'index.html')).write_text('built fixture')
        return ''
    calls = Mock(side_effect=run)
    monkeypatch.setattr(publish, 'run', calls)
    return portal, calls


def test_unregistered_portal_does_not_require_pnpm(builder, monkeypatch):
    monkeypatch.setattr(publish, 'pnpm_command', Mock(side_effect=AssertionError('Must remain optional')))
    outputs = publish.build_frontends()
    assert set(outputs) == {'frontend', 'frontend-pm'}


def test_registered_portal_uses_frozen_lock_and_cache_detects_change(builder):
    portal, calls = builder
    first = publish.build_frontends(include_portal=True)
    assert 'frontend-portal' in first
    assert ['mock-pnpm', 'install', '--frozen-lockfile', '--ignore-scripts'] in [c.args[0] for c in calls.call_args_list]
    assert any(c.args[0][:4] == ['mock-pnpm', 'exec', 'vite', 'build'] for c in calls.call_args_list)
    calls.reset_mock()
    assert publish.build_frontends(include_portal=True) == first
    assert not any('build' in c.args[0] or 'install' in c.args[0] for c in calls.call_args_list)
    (portal / 'source.js').write_text('changed')
    second = publish.build_frontends(include_portal=True)
    assert second['frontend-portal'] != first['frontend-portal']
    assert second['frontend'] == first['frontend']
    (second['frontend-portal'] / 'index.html').write_text('corrupt')
    with pytest.raises(RuntimeError, match='Cached build is corrupt: frontend-portal'):
        publish.build_frontends(include_portal=True)


def test_missing_lock_or_failed_install_does_not_stamp_dependencies(builder, monkeypatch):
    portal, calls = builder
    (portal / 'pnpm-lock.yaml').unlink()
    with pytest.raises(RuntimeError, match='committed pnpm lockfile'): publish.portal_install(portal)
    assert not publish.marker('deps-frontend-portal')
    (portal / 'pnpm-lock.yaml').write_text('lockfileVersion: 9.0')
    monkeypatch.setattr(publish, 'run', Mock(side_effect=RuntimeError('install unavailable')))
    with pytest.raises(RuntimeError): publish.portal_install(portal)
    assert not publish.marker('deps-frontend-portal')
