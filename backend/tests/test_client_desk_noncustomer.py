from datetime import datetime
from types import SimpleNamespace

import pytest

from app.client_desk import link_service, sources
from app.client_desk.models import ClientDeskWaLink
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage
from tests.test_client_desk_business import isolated


def seed(db, monkeypatch, *, account_uid='a', owner=1):
    account = WhatsAppAccount(id=owner, account_uid=account_uid, ark_user_id=owner,
        provider='baileys', session_generation=3, consent_version=2, status='active',
        phone_number='+15550001111', raw_payload={
            'account_uid': account_uid, 'session_generation': 3, 'consent_version': 2,
            'self_identity': {'session_generation': 3, 'pn_jid': '15550001111@s.whatsapp.net',
                              'lid_jid': '123456789@lid'}})
    db.add(account)
    pairs = []
    for n, (jid, label) in enumerate([
        ('123456789@lid', None), ('0@c.us', None),
        ('15550001111:4@s.whatsapp.net', None),
        ('444444444@lid', 'Roxanne'), ('555555555@lid', 'Rytha'),
        ('666666666@lid', 'Gary'), ('777777777@lid', 'Linda'),
        ('888888888@lid', None), ('15550002222@c.us', 'Rina'),
    ], 1):
        conv = WhatsAppConversation(id=n, account_uid=account_uid, conversation_uid=f'c{n}',
            chat_id=jid, contact_name=label, is_group=False,
            raw_payload={'contact_identity_conflict': n in range(4, 9), 'session_generation': 3})
        msg = WhatsAppMessage(id=n, account_uid=account_uid, conversation_uid=f'c{n}',
            message_uid=f'm{n}', external_message_id=f'e{n}', direction='inbound',
            content_text='retained', sent_at=datetime(2026, 11, 14, 10, n))
        db.add_all([conv, msg]); pairs.append((conv, account, [msg]))
    db.commit()
    monkeypatch.setattr(link_service, 'require_enabled', lambda *a, **k: None)
    monkeypatch.setattr(sources, 'visible_wa', lambda *a, **k: pairs)
    return account, pairs


def test_unlinked_excludes_only_verified_self_and_psa_before_counts_and_paging(isolated, monkeypatch):
    db = isolated; account, pairs = seed(db, monkeypatch)
    before = [(c.conversation_uid, c.chat_id, c.raw_payload.copy()) for c, _, _ in pairs]
    result = link_service.conversations(db, 1, page=1, page_size=2)
    assert result['total'] == result['unreplied_count'] == 6
    assert [r['conversation_uid'] for r in result['items']] == ['c9', 'c8']
    assert [r['conversation_uid'] for r in link_service.conversations(db, 1, page=3, page_size=2)['items']] == ['c5', 'c4']
    assert link_service.conversations(db, 1, keyword='Rina')['total'] == 1
    assert before == [(c.conversation_uid, c.chat_id, c.raw_payload) for c, _, _ in pairs]
    assert db.query(WhatsAppMessage).count() == 9
    assert db.query(ClientDeskWaLink).count() == 0
    assert not db.dirty and not db.deleted and not db.new


@pytest.mark.parametrize('scope,kind', [('linked', 'linked'), ('ignored', 'ignored')])
def test_explicit_existing_link_views_are_retained(isolated, monkeypatch, scope, kind):
    db = isolated; seed(db, monkeypatch)
    db.add(ClientDeskWaLink(id=1, account_uid='a', conversation_uid='c1', link_type=kind,
        company_id=801 if kind=='linked' else None, created_by=1))
    db.commit()
    result=link_service.conversations(db,1,scope=scope)
    assert result['total']==1 and result['items'][0]['conversation_uid']=='c1'


@pytest.mark.parametrize('change', ['old_generation', 'other_account', 'missing_identity', 'wrong_type', 'other_owner_identity'])
def test_unproven_identity_never_hides_a_customer(isolated, monkeypatch, change):
    db=isolated; account, _=seed(db, monkeypatch)
    payload=account.raw_payload.copy()
    if change=='old_generation': payload['self_identity']={**payload['self_identity'],'session_generation':2}
    if change=='other_account': payload['account_uid']='other'
    if change=='missing_identity': payload.pop('self_identity')
    if change=='wrong_type': payload['self_identity']='123456789@lid'
    if change=='other_owner_identity': payload['self_identity']={**payload['self_identity'],'lid_jid':'999999999@lid','pn_jid':'15550009999@s.whatsapp.net'}
    account.raw_payload=payload; db.commit()
    result=link_service.conversations(db,1)
    assert 'c1' in [r['conversation_uid'] for r in result['items']]
    assert result['total']==8  # Only the fixed PSA identity can be excluded.


def test_same_rule_applies_to_another_salesperson(isolated, monkeypatch):
    account,_=seed(isolated,monkeypatch,account_uid='salesperson_b',owner=2)
    result=link_service.conversations(isolated,2)
    assert result['total']==6


@pytest.mark.parametrize('generation', [2, None])
def test_prior_or_unknown_generation_customer_is_not_hidden_by_new_number(isolated, monkeypatch, generation):
    account, pairs=seed(isolated,monkeypatch)
    for conv,_,_ in pairs:
        conv.raw_payload={**conv.raw_payload,'session_generation':generation}
    isolated.commit()
    result=link_service.conversations(isolated,1)
    assert result['total']==8
    assert {'c1','c3'} <= {r['conversation_uid'] for r in result['items']}


def test_logged_out_account_cannot_use_pre_logout_identity(isolated, monkeypatch):
    account,_=seed(isolated,monkeypatch)
    account.status='reconnect_required'
    isolated.commit()
    result=link_service.conversations(isolated,1)
    assert result['total']==8
