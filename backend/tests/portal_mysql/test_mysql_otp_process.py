"""T02: separately spawned Python processes compete for one real OTP."""
from datetime import timedelta
import multiprocessing
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal import auth_service as auth
from app.portal.models import AuditEvent, AuthChallenge
from otp_process_worker import run
from test_mysql_concurrency import wait_for_lock
from test_mysql_otp_race import issue, session_count


@pytest.mark.parametrize('scenario', ['valid', 'rollback', 'wrong', 'expired'])
def test_otp_verification_serializes_across_processes(trade, monkeypatch, scenario):
    attempt = issue(trade, monkeypatch)
    clock = auth.beijing_now()
    code = attempt.code
    if scenario == 'wrong':
        code = '000001' if code != '000001' else '000002'
    if scenario == 'expired':
        with Session(trade.engine) as db:
            clock = db.get(AuthChallenge, attempt.identifier).expires_at + timedelta(seconds=1)
    spawn = multiprocessing.get_context('spawn')
    outputs = [spawn.Queue(), spawn.Queue()]
    releases = [spawn.Event(), spawn.Event()]
    releases[1].set()
    workers = [spawn.Process(target=run, args=(trade.engine.url, vars(auth.get_settings()), clock,
        attempt, code, releases[index], outputs[index], index == 1 or scenario != 'rollback'))
        for index in range(2)]
    try:
        workers[0].start()
        first = outputs[0].get(timeout=15)
        assert first[0] == 'connected', first
        assert outputs[0].get(timeout=15) == ('verified', scenario in ('valid', 'rollback'))
        workers[1].start()
        second = outputs[1].get(timeout=15)
        assert second[0] == 'connected', second
        assert len({first[1], second[1], os.getpid()}) == 3
        assert first[2] != second[2]
        wait_for_lock(trade.engine, second[2])
        releases[0].set()
        assert outputs[0].get(timeout=15) == ('finished', scenario in ('valid', 'rollback'))
        if scenario == 'valid':
            assert outputs[1].get(timeout=15) == ('denied', 'AUTH_FAILED', 401)
        else:
            accepted = scenario == 'rollback'
            assert outputs[1].get(timeout=15) == ('verified', accepted)
            assert outputs[1].get(timeout=15) == ('finished', accepted)
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
    finally:
        releases[0].set()
        for worker in workers:
            if worker.pid is not None:
                worker.join(3)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
        for output in outputs:
            output.close()
            output.join_thread()
    with Session(trade.engine) as db:
        challenge = db.get(AuthChallenge, attempt.identifier)
        successful = scenario in ('valid', 'rollback')
        assert session_count(db, trade) == attempt.baseline + int(successful)
        assert (challenge.consumed_at is not None) is successful
        assert challenge.attempts == {'valid': 1, 'rollback': 1, 'wrong': 2, 'expired': 0}[scenario]
        success_audits = db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.trace_id == attempt.preauth_public_id, AuditEvent.action == 'auth.verified'))
        assert success_audits == int(successful)
