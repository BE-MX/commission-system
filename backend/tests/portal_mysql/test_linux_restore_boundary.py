"""Actual listener verification must reject wildcard and mixed SSH bindings."""
import pytest
from linux_restore import verify_loopback_listeners


def test_only_loopback_listeners_pass():
    verify_loopback_listeners(b'LISTEN 0 128 127.0.0.1:45678 0.0.0.0:*\nLISTEN 0 128 [::1]:45678 [::]:*\n', 45678)


@pytest.mark.parametrize('output', [b'', b'LISTEN 0 128 0.0.0.0:45678 0.0.0.0:*\n',
    b'LISTEN 0 128 [::]:45678 [::]:*\n',
    b'LISTEN 0 128 127.0.0.1:45678 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:45678 0.0.0.0:*\n'])
def test_wildcard_or_missing_listener_rejects(output):
    with pytest.raises(AssertionError, match='loopback'):
        verify_loopback_listeners(output, 45678)
