from contextlib import nullcontext
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
import office_release as office


@pytest.mark.parametrize('rollback', [False, True])
def test_forward_and_rollback_allow_cold_start(tmp_path, monkeypatch, rollback):
    clock = [0]
    starts = [0]
    guard = Mock()
    def run(args, **kwargs):
        if args[:3] == ['git', 'rev-parse', 'HEAD']: return 'old'
        if args[1:2] == ['status']: return 'SERVICE_RUNNING'
        if args[1:2] == ['start']: starts[0] += 1; clock[0] = 0
        return ''
    def health(port):
        if rollback and starts[0] == 1: raise OSError('candidate broken')
        if clock[0] < 80: raise OSError('cold import')
    monkeypatch.setattr(office, 'run', run)
    monkeypatch.setattr(office, 'STATE', tmp_path)
    monkeypatch.setattr(office, 'health', health)
    monkeypatch.setattr(office, 'protocol_observation', lambda *a: {})
    monkeypatch.setattr(office, 'rollback_guard', lambda *a: nullcontext(guard))
    monkeypatch.setattr(office.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(office.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    prepared = dict(nssm='nssm', live=tmp_path, revision='new', previous='old',
        backend_changed=True, connector_changed=False, static=[], python='python',
        application=Path('python.exe'), parameters='', port=8001, schema='197')
    if rollback:
        with pytest.raises(RuntimeError, match='readiness deadline'): office.activate_locked(prepared)
        guard.check.assert_called_once()
    else:
        assert office.activate_locked(prepared)['status'] == 'updated'
    assert clock[0] == 80
