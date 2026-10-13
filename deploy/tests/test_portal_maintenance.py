"""Maintenance ownership, unknown outcomes and monitoring failures; no shared writes."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portal_mirror_fence_remote as fence
import portal_maintenance as maintenance


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    for name, path in {'DIRECTORY': tmp_path, 'SCRIPT': tmp_path / 'holder.py',
            'RECORD': tmp_path / 'record.json', 'CRON': tmp_path / 'cron'}.items():
        monkeypatch.setattr(fence, name, path)
    monkeypatch.setattr(fence, 'cron_digest', lambda: 'original-cron')
    monkeypatch.setattr(fence, 'unit_state', lambda: {'ActiveState': 'inactive', 'MainPID': '0'})
    run = Mock(side_effect=AssertionError('No real systemd command allowed'))
    monkeypatch.setattr(fence, 'command', run)
    return run


def baseline(token='a'*32, status='frozen'):
    return {'token': token, 'cron_sha256': 'original-cron', 'status': status}


def test_wrong_owner_cannot_thaw(mirror):
    fence.private_record(baseline())
    with pytest.raises(RuntimeError, match='owner'):
        fence.execute_locked({'action': 'thaw', **baseline('b'*32)})
    mirror.assert_not_called()


def test_lost_thaw_reply_is_safe_to_retry(mirror):
    fence.private_record(baseline())
    request = {'action': 'thaw', **baseline()}
    assert fence.execute_locked(request)['status'] == 'restored'
    assert fence.execute_locked(request)['status'] == 'restored'
    mirror.assert_not_called()


def test_old_receipt_cannot_stop_new_owner(mirror):
    fence.private_record(baseline('b'*32))
    with pytest.raises(RuntimeError, match='owner'):
        fence.execute_locked({'action': 'thaw', **baseline('a'*32, 'restored')})
    mirror.assert_not_called()


def test_cron_drift_keeps_fence(mirror):
    fence.private_record(baseline())
    with pytest.raises(RuntimeError, match='changed'):
        fence.execute_locked({'action': 'thaw', **{**baseline(), 'cron_sha256': 'changed-cron'}})
    assert json.loads(fence.RECORD.read_text())['status'] == 'frozen'
    mirror.assert_not_called()


@pytest.mark.parametrize('body', [
    '* * * * * root node sync-outbound.js # flock /tmp/okki-outbound.lock /root/.openclaw/workspace/okki-sync',
    '* * * * * root flock -u /tmp/okki-outbound.lock sh -c "cd /root/.openclaw/workspace/okki-sync; node sync-outbound.js"',
    '* * * * * root sh -c "echo flock /tmp/okki-outbound.lock; cd /root/.openclaw/workspace/okki-sync; node sync-outbound.js"',
])
def test_unapproved_lock_command_cannot_be_adopted(tmp_path, monkeypatch, body):
    cron = tmp_path / 'cron'
    cron.write_text(body)
    monkeypatch.setattr(fence, 'CRON', cron)
    with pytest.raises(RuntimeError, match='exclusive-lock'):
        fence.cron_digest()


def test_new_manual_process_invalidates_frozen_proof(mirror, monkeypatch):
    fence.private_record(baseline())
    monkeypatch.setattr(fence, 'unit_state', lambda: {'ActiveState': 'active'})
    monkeypatch.setattr(fence, 'verify_holder', lambda *args: None)
    monkeypatch.setattr(fence, 'manual_mirror_running', lambda: True)
    with pytest.raises(RuntimeError, match='manual'):
        fence.execute_locked({'action': 'verify-frozen', **baseline()})


def test_completed_receipt_allows_new_preflight(mirror):
    fence.private_record(baseline(status='restored'))
    assert fence.execute_locked({'action': 'check'})['status'] == 'ready'


def test_unknown_start_result_retains_bound_intent(mirror):
    with pytest.raises(AssertionError, match='No real'):
        fence.execute_locked({'action': 'freeze', **baseline()})
    assert json.loads(fence.RECORD.read_text()) == baseline(status='starting')


class Result:
    def __init__(self, value): self.value = value
    def one(self): return self.value


class Monitor:
    def __init__(self, values, lost='0'): self.values = iter(values); self.lost = lost
    def scalar(self, query): return next(self.values)
    def execute(self, query): return Result(('Performance_schema_thread_instances_lost', self.lost))


@pytest.mark.parametrize('values, lost, message', [([0], '0', 'Schema'),
    ([1, 0], '0', 'absent'), ([1, 1, 0], '0', 'monitoring'), ([1, 1, 1], '1', 'Lost')])
def test_missing_thread_evidence_cannot_pass_as_zero_workers(values, lost, message):
    with pytest.raises(RuntimeError, match=message):
        maintenance.event_threads_visible(Monitor(values, lost))


def test_full_monitoring_evidence_passes():
    maintenance.event_threads_visible(Monitor([1, 1, 1]))
