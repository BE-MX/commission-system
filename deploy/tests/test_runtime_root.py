"""A prepared deployer must target the installed checkout, never its own worktree."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_root import resolve_live_root


def test_normal_entry_keeps_installed_root(tmp_path):
    assert resolve_live_root([], tmp_path / 'deploy/publish.py') == tmp_path


def test_candidate_entry_keeps_live_state_and_pinned_source(tmp_path):
    live = tmp_path / 'installed service'
    revision = 'a' * 40
    script = live / '.deploy_state/sources' / revision / 'deploy/publish.py'
    assert resolve_live_root(['--live-root', str(live), '--revision', revision,
                              '--no-pull', '--prepare-only'], script) == live


@pytest.mark.parametrize('extra', [[], ['--revision', 'short'], ['--revision', 'b' * 40],
                                 ['--revision', 'a' * 40, '--cloud-only'],
                                 ['--revision', 'a' * 40, '--office-lan-https', 'plan.json'],
                                 ['--revision', 'a' * 40, '--migrate-only', 'plan.json']])
def test_candidate_entry_rejects_unpinned_mismatched_or_partial_release(tmp_path, extra):
    script = tmp_path / '.deploy_state/sources' / ('a' * 40) / 'deploy/publish.py'
    with pytest.raises(RuntimeError):
        resolve_live_root(['--live-root', str(tmp_path), *extra], script)


def test_candidate_entry_rejects_unmanaged_runtime(tmp_path):
    with pytest.raises(RuntimeError):
        resolve_live_root(['--live-root', str(tmp_path), '--revision', 'a' * 40],
                          tmp_path / 'unmanaged/deploy/publish.py')


def test_fresh_process_loads_candidate_modules_but_uses_installed_state(tmp_path):
    live = tmp_path / 'installed service'
    revision = 'a' * 40
    candidate = live / '.deploy_state/sources' / revision
    shutil.copytree(Path(__file__).resolve().parents[1], candidate / 'deploy',
                    ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    code = '''
import json, sys
sys.path.insert(0, sys.argv.pop(1))
import publish, office_release, schema_release, cloud_backend, remote_backend
print(json.dumps({'root': str(publish.ROOT), 'state': str(publish.STATE),
 'office_root': str(office_release.ROOT), 'schema_state': str(schema_release.STATE),
 'default_cwd': str(publish.run.__defaults__[0]),
 'modules': [m.__file__ for m in (publish, office_release, schema_release, cloud_backend, remote_backend)]}))
'''
    result = subprocess.run([sys.executable, '-c', code, str(candidate / 'deploy'),
                             '--live-root', str(live), '--revision', revision],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert Path(data['root']) == Path(data['office_root']) == Path(data['default_cwd']) == live
    assert Path(data['state']) == Path(data['schema_state']) == live / '.deploy_state'
    assert all(Path(module).parent == candidate / 'deploy' for module in data['modules'])
    assert not (live / '.deploy_state/publish-current.json').exists()


@pytest.mark.parametrize('flag', ['--cloud-o', '--migrate-o'])
def test_cli_rejects_abbreviations_before_creating_publish_state(tmp_path, flag):
    revision = 'a' * 40
    candidate = tmp_path / '.deploy_state/sources' / revision
    shutil.copytree(Path(__file__).resolve().parents[1], candidate / 'deploy',
                    ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    result = subprocess.run([sys.executable, str(candidate / 'deploy/publish.py'),
                             '--live-root', str(tmp_path), '--revision', revision, flag],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'unrecognized arguments' in result.stderr
    assert not (tmp_path / '.deploy_state/publish-current.json').exists()
    assert not (tmp_path / '.deploy_state/publish.lock').exists()
