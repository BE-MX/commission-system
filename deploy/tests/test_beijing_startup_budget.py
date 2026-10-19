"""Cold start and recovery budgets, using a virtual clock and isolated receipts."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import remote_backend as backend


@pytest.mark.parametrize('case', ['forward', 'rollback', 'unchanged', 'schema_failure', 'partial_stop'])
def test_readiness_never_confuses_cold_start_with_failed_rollback(tmp_path, monkeypatch, case):
    revision, previous = 'a' * 40, 'b' * 40
    (tmp_path / ('backend-prepared-' + revision + '.json')).write_text(json.dumps(dict(
        revision=revision, previous=previous, schema='197', changed=case != 'unchanged',
        schema_changed=case == 'schema_failure', environment=None)))
    clock, starts, commands = [0], [0], []
    def run(args, **kwargs):
        commands.append(args)
        if case == 'partial_stop' and args[:4] == ['sudo', '-n', 'systemctl', 'stop']:
            if sum(c[:4] == ['sudo', '-n', 'systemctl', 'stop'] for c in commands) == 1:
                raise RuntimeError('stop response lost')
        if args[:2] == ['git', 'rev-parse']: return previous
        if args[:4] == ['sudo', '-n', 'systemctl', 'start']:
            starts[0] += 1
            clock[0] = 0
        return ''
    def healthy():
        if case == 'schema_failure' or (case == 'rollback' and starts[0] == 1):
            raise OSError('candidate unavailable')
        if clock[0] < 90: raise OSError('still starting')
    guard = Mock()
    monkeypatch.setattr(backend, 'ROOT', tmp_path)
    monkeypatch.setattr(backend, 'STATE', tmp_path)
    monkeypatch.setattr(backend, 'run', run)
    monkeypatch.setattr(backend, 'healthy', healthy)
    monkeypatch.setattr(backend, 'schema_check', Mock())
    monkeypatch.setattr(backend, 'protocol_observation', lambda *_: {})
    monkeypatch.setattr(backend, 'rollback_guard', lambda *_: nullcontext(guard))
    monkeypatch.setattr(backend.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backend.time, 'sleep', lambda n: clock.__setitem__(0, clock[0] + n))
    if case in {'rollback', 'schema_failure', 'partial_stop'}:
        with pytest.raises(RuntimeError): backend.activate_locked(revision)
    else:
        backend.activate_locked(revision)
    if case == 'schema_failure':
        assert starts[0] == 1 and not guard.check.called
        assert not any(c[:2] == ['git', 'checkout'] and c[-1] == previous for c in commands)
    else:
        assert clock[0] == 90
        assert starts[0] == {'forward': 1, 'rollback': 2, 'unchanged': 0, 'partial_stop': 1}[case]
        if case in {'rollback', 'partial_stop'}: guard.check.assert_called_once()


def test_availability_evidence_uses_beijing_time_across_utc_midnight(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 18, 16, 0, 1, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(backend, 'datetime', Clock)
    backend.service_event(tmp_path, 'office', 'a' * 40, 'b' * 40, 'http-ready')
    path = next(tmp_path.glob('*service-events*.json'))
    assert json.loads(path.read_text())[0]['at'] == '2026-10-19T00:00:01+08:00'
    path.write_text('{}')
    backend.service_event(tmp_path, 'office', 'a' * 40, 'b' * 40, 'http-ready')
    assert path.read_text() == '{}'  # Corrupt telemetry cannot stop a deployment.
