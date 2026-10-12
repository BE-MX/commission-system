"""Opening customer access must not take over the existing outbound executor."""
from unittest.mock import Mock

import pytest

from app.core.config import Settings


@pytest.mark.parametrize('portal,worker', [(False, False), (False, True), (True, False), (True, True)])
def test_bootstrap_requires_explicit_worker_opt_in(monkeypatch, portal, worker):
    from app.bootstrap import portal_outbound
    settings = Settings(_env_file=None).model_copy(update={
        'PORTAL_ENABLED': portal, 'PORTAL_OUTBOUND_WORKER_ENABLED': worker})
    initialize = Mock(return_value='legacy')
    monkeypatch.setattr(portal_outbound, 'get_settings', lambda: settings)
    monkeypatch.setattr(portal_outbound, 'initialize', initialize)
    assert portal_outbound.initialize_portal_outbound() == 'legacy'
    assert initialize.call_args.kwargs['portal_enabled'] is (portal and worker)


@pytest.mark.parametrize('mode', ['legacy', 'outbound-worker-v1'])
def test_customer_access_registers_mail_without_registering_outbound(monkeypatch, mode):
    from app.schedulers import registry
    settings = Settings(_env_file=None).model_copy(update={
        'PORTAL_ENABLED': True, 'PORTAL_OUTBOUND_WORKER_ENABLED': False,
        'PORTAL_NOTIFICATION_ENABLED': True, 'OKKI_OUTBOUND_AUTO_ENABLED': True,
        'OKKI_CLIENT_ID': 'isolated', 'OKKI_CLIENT_SECRET': 'isolated',
    })
    monkeypatch.setattr(registry, 'get_settings', lambda: settings)
    scheduler = Mock()
    registry._register_jobs(scheduler, outbound_mode=mode)
    jobs = {call.kwargs['id'] for call in scheduler.add_job.call_args_list}
    assert registry.JOB_PORTAL_AUTH_MAIL not in jobs
    assert registry.JOB_PORTAL_AUTH_CLEANUP in jobs
    assert registry.JOB_PORTAL_NOTIFICATIONS in jobs
    assert registry.JOB_PORTAL_OUTBOUND not in jobs
    assert (registry.JOB_OKKI_OUTBOUND_RECONCILE in jobs) is (mode == 'legacy')
    assert registry.JOB_OKKI_OUTBOUND_DELETE_RECONCILE in jobs


def test_explicit_worker_requires_confirmed_mode_even_when_scheduler_disabled(monkeypatch):
    from app.schedulers import registry
    settings = Settings(_env_file=None).model_copy(update={'PORTAL_ENABLED': True,
        'PORTAL_OUTBOUND_WORKER_ENABLED': True, 'SCHEDULER_ENABLED': False})
    monkeypatch.setattr(registry, 'get_settings', lambda: settings)
    with pytest.raises(RuntimeError, match='Outbound mode'):
        registry.start_scheduler(outbound_mode='legacy')
    assert registry.start_scheduler(outbound_mode='outbound-worker-v1') is None


def test_customer_access_can_keep_legacy_when_scheduler_disabled(monkeypatch):
    from app.schedulers import registry
    settings = Settings(_env_file=None).model_copy(update={'PORTAL_ENABLED': True,
        'PORTAL_OUTBOUND_WORKER_ENABLED': False, 'SCHEDULER_ENABLED': False})
    monkeypatch.setattr(registry, 'get_settings', lambda: settings)
    assert registry.start_scheduler(outbound_mode='legacy') is None
    with pytest.raises(RuntimeError, match='Outbound mode'):
        registry.start_scheduler(outbound_mode='unknown')


@pytest.mark.parametrize('portal,worker', [(False, False), (False, True), (True, False)])
def test_direct_outbound_callback_cannot_install_mode_without_opt_in(monkeypatch, portal, worker):
    from app.invoice import outbound_worker
    settings = Settings(_env_file=None).model_copy(update={
        'PORTAL_ENABLED': portal, 'PORTAL_OUTBOUND_WORKER_ENABLED': worker})
    factory = Mock(side_effect=AssertionError('Disabled worker must not open a session'))
    monkeypatch.setattr(outbound_worker, 'get_settings', lambda: settings)
    assert outbound_worker.run_once(factory) == {'status': 'disabled', 'processed': 0}
    factory.assert_not_called()
