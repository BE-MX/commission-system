"""Durable legacy POST gates. Tickets never authorize recovery or a second POST."""
from dataclasses import dataclass, field
import logging
from threading import Lock

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.commerce_transition import service as ownership
from app.commerce_transition.models import ClaimEvidence, SendingClaim
from app.invoice import transition_gate
from app.portal.authority import lock_authority

logger = logging.getLogger(__name__)


@dataclass
class SendTicket:
    request_key: str
    claim_id: int
    invoice_id: int
    epoch: int
    payload_hash: str
    consumed: bool = False
    lock: Lock = field(default_factory=Lock, repr=False)


def authorize(db, invoice, expected_epoch=None, *, confirm=False):
    # The same order applies to employee, background and evidence writers.
    lock_authority(db, force=True)
    authority = transition_gate.require_invoice(db, invoice, 'legacy', expected_epoch)
    if confirm:
        authority = ownership.confirm_authority(db, authority.invoice_id, 'legacy', authority.epoch,
            {'legacy_formal_command': True})
    return authority


def start(db, invoice, request_key, operation, payload, responsibilities, expected_epoch=None):
    authority = authorize(db, invoice, expected_epoch, confirm=True)
    from app.inventory.legacy_scope import require_legacy_outbound_scope
    require_legacy_outbound_scope(db, operation, payload)
    result = ownership.begin_send(db, authority.invoice_id, request_key, operation, payload,
        authority.epoch, route='legacy', responsibilities=responsibilities)
    if not result.created:
        raise ownership.TransitionError('原发送身份已经使用，只能核对原请求，禁止再次外发')
    return SendTicket(request_key, result.claim.id, authority.invoice_id, authority.epoch, result.claim.payload_hash)


def find(db, request_key):
    return db.scalar(select(SendingClaim).where(SendingClaim.request_key == request_key)
                     .execution_options(populate_existing=True))


def finish(db, request_key, outcome, evidence, external_id=None):
    # Original evidence survives scope revocation, freezing and epoch changes.
    lock_authority(db, force=True)
    ownership.lock_policy(db)
    claim = find(db, request_key)
    if claim is None:
        return None  # A pre-install historical observation must still be retained by its original ledger.
    prior = db.scalar(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id,
        ClaimEvidence.outcome == outcome, ClaimEvidence.external_id == external_id))
    if prior is not None and prior.evidence == evidence:
        return claim
    return ownership.finish_send(db, claim.id, outcome, evidence, external_id=external_id)


def observe_formal(db, request_key, action, outcome, result_row=None, actor_id=None, evidence_ref=None, command_input=None):
    from app.commerce_shadow import hooks
    if not hooks.enabled(db):
        return None
    claim = find(db, request_key)
    if claim is None:
        return None
    actor_id = actor_id or (claim.responsibilities or {}).get('actor_id')
    if not actor_id:
        logger.warning('Legacy comparison lacks original actor claim=%s; coverage remains unobserved', claim.id)
        print(f'[legacy-sending] comparison actor unavailable claim={claim.id}', flush=True)
        return None
    return hooks.external_result(db, claim=claim, action=action, outcome=outcome, result_row=result_row,
        actor_id=int(actor_id), evidence_ref=evidence_ref or {'claim_id': claim.id},
        command_input=command_input if command_input is not None else (claim.responsibilities or {}).get('command_input'))


def _remember(db, ticket, outcome, evidence, external_id=None):
    for retry in range(3):
        try:
            claim = finish(db, ticket.request_key, outcome, evidence, external_id)
            if claim is not None:
                action = 'legacy.order.push' if claim.operation == 'order_push' else 'legacy.receipt.remote' if claim.operation == 'receipt_push' else 'legacy.contract.remote' if claim.operation == 'freight_order_create' else 'legacy.outbound.remote'
                observe_formal(db, ticket.request_key, action, 'rejected' if outcome == 'failed' else 'unknown',
                    evidence_ref={'claim_id': claim.id, 'provider_outcome': outcome})
            db.commit()
            return
        except SQLAlchemyError:
            db.rollback()
            logger.warning('Legacy POST original evidence persistence retry %s', retry + 1)
            print(f'[legacy-sending] original evidence persistence retry {retry + 1}', flush=True)
    raise ownership.TransitionError('原发送证据暂不可持久保存，请核对原任务，禁止重新发送')


def _consume(db, ticket, payload):
    if not isinstance(ticket, SendTicket) or ownership.digest(payload) != ticket.payload_hash:
        raise ownership.TransitionError('外发缺少同载荷的持久办理权凭证')
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise ownership.TransitionError('持久发送责任必须提交后才可HTTP外发')
    # A caller may have rolled back its preparation. An in-memory ticket alone
    # must never turn that abandoned preparation into a remote write.
    with ticket.lock:
        if ticket.consumed:
            raise ownership.TransitionError('发送凭证已使用，禁止重复外发')
        persisted = find(db, ticket.request_key)
        valid = persisted is not None and (persisted.id, persisted.invoice_id, persisted.route,
            persisted.epoch, persisted.payload_hash, persisted.state) == (
            ticket.claim_id, ticket.invoice_id, 'legacy', ticket.epoch, ticket.payload_hash, 'sending')
        db.rollback()
        if not valid:
            raise ownership.TransitionError('原发送责任未持久提交或已进入核对状态，禁止外发')
        ticket.consumed = True


def removal_payload(kind, identity):
    if kind not in {'order','receipt','outbound'} or not str(identity).isdigit() or int(identity)<1:
        raise ownership.TransitionError('原删除对象身份不完整')
    return {'object_type':kind,'external_id':str(identity)}


def start_removal(db, invoice, request_key, kind, identity, responsibilities, expected_epoch=None):
    return start(db,invoice,request_key,kind+'_remove',removal_payload(kind,identity),responsibilities,expected_epoch)


def invoke_removal(db, tickets, kind, identity, send):
    """One typed destructive HTTP effect may own several exact invoice routes."""
    from app.invoice import okki_client
    grants=tickets if isinstance(tickets,(list,tuple)) else [tickets]
    if not grants:raise ownership.TransitionError('删除缺少原订单持久发送责任')
    payload=removal_payload(kind,identity)
    for ticket in grants:_consume(db,ticket,payload)
    outcome='unknown'
    evidence={'original_remove':payload}
    try:
        result=send()
        # The raw parser accepts only documented deletion/absence acknowledgments.
        if result is True or result is None:outcome='succeeded'
        evidence['response_hash']=ownership.digest(result)
        return result
    except Exception as error:
        if (isinstance(error,okki_client.OkkiApiError) and not isinstance(error,okki_client.OkkiOutcomeUncertainError)
                or getattr(error,'uncertain',None) is False):
            outcome='failed';evidence['definitive_original_request_result']=True
        evidence['error_class']=type(error).__name__
        raise
    finally:
        db.rollback()
        for ticket in grants:_remember(db,ticket,outcome,evidence,str(identity))


def invoke(db, ticket, path, token, payload, *, context):
    from app.invoice import okki_client
    _consume(db,ticket,payload)
    outcome, reference, evidence = 'unknown', None, {'request_key': ticket.request_key, 'path': path}
    try:
        result = okki_client._post_json(path, token, payload, context=context)
        if result is None:
            outcome = 'failed'
            evidence.update(auth_rejected=True, definitive_original_request_result=True)
        elif isinstance(result, dict):
            field = {'/v1/invoices/order/push': 'order_id', '/v1/invoices/outbound/push': 'outbound_invoice_id',
                     '/v1/invoices/receipt/push': 'cash_collection_id'}.get(path)
            candidate = str(result.get(field) or '')
            expected = payload.get(field)
            if candidate.isdigit() and int(candidate) > 0 and (expected is None or str(expected) == candidate):
                if field != 'cash_collection_id' or result.get('cash_collection_no'):
                    outcome, reference = 'succeeded', candidate
            evidence['response_hash'] = ownership.digest(result)
        return result
    except okki_client.OkkiOutcomeUncertainError:
        evidence['transport_outcome'] = 'unknown'
        raise
    except okki_client.OkkiApiError:
        outcome = 'failed'
        evidence.update(provider_rejected=True, definitive_original_request_result=True)
        raise
    except Exception:
        evidence['transport_outcome'] = 'unknown'
        raise
    finally:
        db.rollback()  # Never carry business or authority locks across HTTP or late evidence.
        _remember(db, ticket, outcome, evidence, reference)
