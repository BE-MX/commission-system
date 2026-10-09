"""Independent fixture applications retain real shared-IP quotas and resend cooldown."""
from uuid import uuid4
import pytest
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.portal import auth_service as auth
from app.portal.errors import PortalError
from app.portal.models import Account,AuthChallenge,OutboxEvent,RateBucket
from app.portal.schemas import ChallengeInput
from app.portal.security import keyed_digest


@pytest.mark.parametrize('application_case',[0,1])
def test_each_fixture_keeps_real_shared_ip_send_quota(trade,application_case):
    # Same IP across separate fixture applications; never alter quota, time or buckets.
    ip='127.255.255.254'
    with Session(trade.engine) as db:
        preauth,token,csrf=auth.bootstrap(db,ip);db.commit()
        before=db.scalar(select(func.count()).select_from(OutboxEvent));db.rollback()
        for _ in range(30):
            challenge=auth.challenge(db,auth.require_preauth(db,token,csrf),
                ChallengeInput(email=uuid4().hex+'@example.test',purpose='login'),ip)
            assert challenge.account_id is None
            db.commit()
        with pytest.raises(PortalError) as caught:
            auth.challenge(db,auth.require_preauth(db,token,csrf),
                ChallengeInput(email=uuid4().hex+'@example.test',purpose='login'),ip)
        assert caught.value.code=='RATE_LIMITED' and caught.value.status==429
        db.rollback()
        digest=keyed_digest(auth.get_settings().PORTAL_OTP_SECRET,'rate','send-ip:'+ip)
        buckets=db.scalars(select(RateBucket).where(RateBucket.scope_key_hash==digest)).all()
        assert len(buckets)==1 and buckets[0].count==30
        assert db.scalar(select(func.count()).select_from(OutboxEvent))==before


def test_fixture_secret_does_not_remove_real_email_resend_cooldown(trade):
    with Session(trade.engine) as db:
        email=db.get(Account,trade.account_id).email_normalized
        before=(db.scalar(select(func.count()).select_from(AuthChallenge)),db.scalar(select(func.count()).select_from(OutboxEvent)))
        preauth,token,csrf=auth.bootstrap(db,'127.0.0.2');db.commit()
        with pytest.raises(PortalError) as caught:
            auth.challenge(db,auth.require_preauth(db,token,csrf),ChallengeInput(email=email,purpose='login'),'127.0.0.2')
        assert caught.value.code=='RATE_LIMITED' and caught.value.status==429
        db.rollback()
        assert (db.scalar(select(func.count()).select_from(AuthChallenge)),db.scalar(select(func.count()).select_from(OutboxEvent)))==before
