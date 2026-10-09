"""Scoped reads of original customer command receipts, never command execution."""
from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.portal import auth_service as auth, authority
from app.portal.errors import reject
from app.portal.models import CommandReceipt, OrderRequest, PiAmendment, Revision
from app.portal.schemas import Hash, PortalInput


class ActionReceiptQuery(PortalInput):
    action: Literal['cancel', 'accept_proposal', 'reject_proposal', 'accept_pi', 'reject_pi']
    payload_hash: Hash
    revision_id: UUID | None = None
    proposal_hash: Hash | None = None

    @model_validator(mode='after')
    def conditional_revision(self):
        if self.action == 'cancel':
            if self.revision_id is not None or self.proposal_hash is not None:
                raise ValueError('Cancellation does not accept a proposal locator')
        elif self.revision_id is None or self.proposal_hash is None:
            raise ValueError('A proposal revision and content hash are required')
        return self


_ACTIONS = {'cancel':'cancel', 'accept_proposal':'accept', 'reject_proposal':'reject_proposal',
    'accept_pi':'pi_accepted', 'reject_pi':'pi_rejected'}
_AMENDMENT_STATES = frozenset({'current', 'withdrawn', 'pending_customer', 'accepted'})


def query(db, token, public_id, locator: ActionReceiptQuery):
    """Caller commits only auth idle renewal. A miss is not proof of nonexecution.

    The current customer authority barrier precedes the scoped order read lock;
    every receipt/current-state read uses the same transaction. No supplier,
    invoice, inventory, pricing or state-transition helper runs here.
    """
    # This new public query owns a fresh request boundary. Never commit or
    # autoflush unrelated caller state through the router's idle-renewal commit.
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        reject('TRANSACTION_CONFLICT', 'Reload the original request before checking its result.', 409)
    try:
        principal, _ = auth.authenticate(db, token)
        principal.require('cancel' if locator.action == 'cancel' else
            'accept' if locator.action.startswith('accept') else 'reject')
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(public_id),
            OrderRequest.access_id == principal.access.id).with_for_update(read=True)
            .execution_options(populate_existing=True))
        if order is None:
            reject('RESOURCE_NOT_FOUND', 'This order request is not available.', 404)
        command = {'request_id':order.public_id, 'action':locator.action, 'payload_hash':locator.payload_hash}
        key = 'cancel'
        if locator.action != 'cancel':
            revision = db.scalar(select(Revision).where(Revision.public_id == str(locator.revision_id),
                Revision.request_id == order.id,
                Revision.kind == ('pi_amendment' if locator.action.endswith('_pi') else 'proposal'))
                .with_for_update(read=True).execution_options(populate_existing=True))
            if revision is None:
                reject('RESOURCE_NOT_FOUND', 'This proposal is not available.', 404)
            command.update(revision_id=revision.public_id, proposal_hash=locator.proposal_hash)
            if revision.content_hash != locator.proposal_hash:
                return {'found':False, 'command':command}
            key = revision.public_id + (':'+locator.proposal_hash if locator.action.startswith('accept') else '')
        saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == _ACTIONS[locator.action],
            CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == key,
            CommandReceipt.payload_hash == locator.payload_hash).with_for_update(read=True)
            .execution_options(populate_existing=True))
        if saved is None:
            return {'found':False, 'command':command}
        receipt = {'replayed':True, 'original_receipt':deepcopy(saved.result_reference_json),
            'current_state':order.status, 'row_version':order.row_version}
        if locator.action.endswith('_pi'):
            amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id,
                PiAmendment.invoice_id == order.invoice_id).with_for_update(read=True)
                .execution_options(populate_existing=True))
            if amendment is None or amendment.status not in _AMENDMENT_STATES:
                reject('SERVICE_UNAVAILABLE', 'The original PI action result cannot be confirmed.', 503)
            receipt['amendment_state'] = amendment.status
        # Intentionally preserve same-company replay authorization. The original
        # actor reference is not an extra read restriction absent from POST replay.
        return {'found':True, 'command':command, 'receipt':receipt}
    except SQLAlchemyError as error:
        authority.unavailable(error)