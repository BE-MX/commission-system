"""Exercise the real deployment pipe protocol without remote services."""
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
import okki_outbound_remote as remote


def fence_with_line(line):
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    fence.child = SimpleNamespace(stdout=io.StringIO(line))
    return fence


def test_only_fixed_ready_lock_contention_is_retryable():
    with pytest.raises(remote.ModeFenceBusy):
        fence_with_line('{"fence_error":"lock_busy"}\n')._read('ready')
    with pytest.raises(remote.ModeFenceError) as error:
        fence_with_line('{"fence_error":"lock_busy"}\n')._read('checked')
    assert not isinstance(error.value, remote.ModeFenceBusy)
    assert 'checked' in str(error.value)


@pytest.mark.parametrize('line', ['', '{"fence_error":"unavailable"}\n',
                                 '{"fence_error":"SECRET_VALUE"}\n', 'SECRET_VALUE\n'])
def test_unavailable_or_malformed_response_is_sanitized_and_not_retried(line):
    with pytest.raises(remote.ModeFenceError) as error:
        fence_with_line(line)._read('ready')
    assert not isinstance(error.value, remote.ModeFenceBusy)
    assert 'ready' in str(error.value) and 'SECRET_VALUE' not in str(error.value)


def test_busy_connection_is_closed_before_fresh_success(monkeypatch):
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    first, second = object(), object()
    launch = Mock(side_effect=[first, second])
    monkeypatch.setattr(remote.subprocess, 'Popen', launch)
    monkeypatch.setattr(remote.time, 'sleep', Mock())
    closed = []
    monkeypatch.setattr(fence, '_abort', lambda: closed.append(fence.child))
    observation = {'mode':'legacy','database_fingerprint':'e'*64}
    read = Mock(side_effect=[remote.ModeFenceBusy('busy'), observation])
    monkeypatch.setattr(fence, '_read', read)
    assert fence.__enter__() is fence
    assert fence.observation == observation and closed == [first]
    assert fence.child is second and launch.call_count == 2


def test_persistent_busy_fails_with_all_connections_closed(monkeypatch):
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    launch = Mock(side_effect=[object(), object()])
    monkeypatch.setattr(remote.subprocess, 'Popen', launch)
    now = [0]
    monkeypatch.setattr(remote.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(remote.time, 'sleep', Mock())
    abort = Mock(); monkeypatch.setattr(fence, '_abort', abort)
    def busy(*args, **kwargs):
        now[0] += 16
        raise remote.ModeFenceBusy('busy')
    monkeypatch.setattr(fence, '_read', busy)
    with pytest.raises(remote.ModeFenceError, match='remained busy'):
        fence.__enter__()
    assert launch.call_count == abort.call_count == 2


def test_unknown_ready_failure_never_retries(monkeypatch):
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    launch = Mock(); monkeypatch.setattr(remote.subprocess, 'Popen', launch)
    abort = Mock(); monkeypatch.setattr(fence, '_abort', abort)
    monkeypatch.setattr(fence, '_read', Mock(side_effect=remote.ModeFenceError('ready failed')))
    with pytest.raises(remote.ModeFenceError, match='ready failed'):
        fence.__enter__()
    assert launch.call_count == abort.call_count == 1


def test_check_error_keeps_phase_without_replaying_command():
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    fence.child = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO('invalid\n'))
    with pytest.raises(remote.ModeFenceError, match='checked'):
        fence.check()
    assert fence.child.stdin.getvalue() == 'check\n'


@pytest.mark.parametrize('case', ['late_ready', 'busy_at_deadline', 'slow_spawn'])
def test_acquisition_never_succeeds_or_restarts_past_deadline(monkeypatch, case):
    fence = remote.ModeFence(Path('/owned'), Path('/protected'))
    now = [0]
    monkeypatch.setattr(remote.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(remote.time, 'sleep', lambda seconds: now.__setitem__(0, now[0]+seconds))
    def spawn(*args, **kwargs):
        if case == 'slow_spawn': now[0] = 31
        return object()
    launch = Mock(side_effect=spawn);monkeypatch.setattr(remote.subprocess, 'Popen', launch)
    abort = Mock();monkeypatch.setattr(fence, '_abort', abort)
    def ready(phase, *, timeout):
        assert 0 < timeout <= 30
        if case == 'late_ready':
            now[0] = 31
            return {'mode':'legacy','database_fingerprint':'e'*64}
        now[0] = 29.9
        raise remote.ModeFenceBusy('busy')
    read = Mock(side_effect=ready);monkeypatch.setattr(fence, '_read', read)
    with pytest.raises(remote.ModeFenceError, match='deadline'):
        fence.__enter__()
    assert launch.call_count == abort.call_count == 1
    assert read.call_count == (0 if case == 'slow_spawn' else 1)
