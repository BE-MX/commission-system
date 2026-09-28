"""Protect the cutover boundaries without connecting to production."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_cloud_migration as migration


def test_final_copy_deletes_stale_state_only_within_each_named_root(monkeypatch):
    calls = []
    monkeypatch.setattr(migration.subprocess, 'run', lambda args, **kwargs:
                        calls.append(args) or SimpleNamespace(returncode=0, stdout='', stderr=''))
    roots = ['root/.openclaw', 'root/.mcporter', 'opt/deputy-relay', 'var/lib/ark-agent-migration/source']
    migration.direct_transfer(roots, final=True)
    assert len(calls) == 4
    for root, call in zip(roots, calls):
        command = call[-1]
        assert '--delete' in command and '--checksum' in command
        assert migration.TARGET + ':/' + root + '/' in command
        assert '-azR' not in command


def test_final_copy_refuses_unbounded_delete(monkeypatch):
    monkeypatch.setattr(migration.subprocess, 'run', lambda *args, **kwargs: pytest.fail('SSH must not run'))
    with pytest.raises(ValueError):
        migration.direct_transfer(['root'], final=True)


def test_activation_rechecks_live_source_and_blocks_changed_freeze(monkeypatch, tmp_path):
    monkeypatch.setattr(migration, 'STATE', tmp_path)
    (tmp_path / 'frozen-copy.json').write_text(json.dumps({'freeze_id': 'old-freeze'}))
    calls = []
    monkeypatch.setattr(migration, 'invoke', lambda host, action:
                        calls.append((host, action)) or {'freeze_id': 'new-freeze'})
    with pytest.raises(RuntimeError, match='does not match'):
        migration.execute('activate-target')
    assert calls == [(migration.SOURCE, 'verify-frozen')]


def test_freeze_requires_validated_staged_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(migration, 'STATE', tmp_path)
    monkeypatch.setattr(migration, 'invoke', lambda *args: pytest.fail('Must not pause source'))
    with pytest.raises(RuntimeError, match='Validate staged'):
        migration.execute('freeze-source')
