"""Actual listener verification must reject wildcard and mixed SSH bindings."""
import pytest
from subprocess import CompletedProcess
from linux_restore import verify_loopback_listeners, verify_owned_identity


def test_only_loopback_listeners_pass():
    verify_loopback_listeners(b'LISTEN 0 128 127.0.0.1:45678 0.0.0.0:*\nLISTEN 0 128 [::1]:45678 [::]:*\n', 45678)


@pytest.mark.parametrize('output', [b'', b'LISTEN 0 128 0.0.0.0:45678 0.0.0.0:*\n',
    b'LISTEN 0 128 [::]:45678 [::]:*\n',
    b'LISTEN 0 128 127.0.0.1:45678 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:45678 0.0.0.0:*\n'])
def test_wildcard_or_missing_listener_rejects(output):
    with pytest.raises(AssertionError, match='loopback'):
        verify_loopback_listeners(output, 45678)


def test_transient_identity_handshake_retries_without_relaxing_target():
    results = iter([CompletedProcess([], 1, b'', b'ERROR 2013 (HY000): lost connection'),
        CompletedProcess([], 0, b'owned-uuid\t45678\tOFF\n', b'')])
    pauses = []
    verify_owned_identity(lambda: next(results), ['owned-uuid', '45678', 'OFF'], pauses.append)
    assert pauses == [.5]


@pytest.mark.parametrize('identity', [b'other-uuid\t45678\tOFF\n',
    b'owned-uuid\t3306\tOFF\n', b'owned-uuid\t45678\tON\n'])
def test_identity_mismatch_never_retries(identity):
    calls = []
    def probe():
        calls.append(1)
        return CompletedProcess([], 0, identity, b'')
    with pytest.raises(AssertionError, match='target changed'):
        verify_owned_identity(probe, ['owned-uuid', '45678', 'OFF'], lambda _: pytest.fail('Must not retry mismatch'))
    assert calls == [1]


def test_handshake_retries_are_bounded():
    calls = []
    def probe():
        calls.append(1)
        return CompletedProcess([], 1, b'', b'ERROR 2003 (HY000): cannot connect')
    with pytest.raises(AssertionError, match='no restore SQL'):
        verify_owned_identity(probe, ['owned-uuid', '45678', 'OFF'], lambda _: None)
    assert len(calls) == 3


def test_authentication_error_does_not_retry():
    result = CompletedProcess([], 1, b'', b'ERROR 1045 (28000): access denied')
    with pytest.raises(AssertionError, match='no restore SQL'):
        verify_owned_identity(lambda: result,
            ['owned-uuid', '45678', 'OFF'], lambda _: pytest.fail('Must not retry authentication'))
    assert result.stderr == b''
