"""Public portal model registration; no relationship eagerly loads private records."""

from app.portal.identity_models import (Account, AuthChallenge, AuthorityBarrier,
    CustomerAccess, HistoryGrant, Invitation, Membership, PortalSession,
    PreauthSession, RateBucket, Site)
from app.portal.catalog_models import CatalogGrant, CatalogItem, MappingRevision
from app.portal.order_models import (CommandReceipt, Conversion, OrderRequest,
    PiAmendment, Publication, Quote, RequestLine, Revision)
from app.portal.event_models import AuditEvent, OutboxEvent
from app.portal.immutability import install_guards

install_guards()
from app.portal.invoice_lifecycle import install_guard as install_invoice_guard
install_invoice_guard()

__all__ = ["Account", "AuthChallenge", "AuthorityBarrier", "CustomerAccess",
    "HistoryGrant", "Invitation", "Membership", "PortalSession", "PreauthSession",
    "RateBucket", "Site", "CatalogGrant", "CatalogItem", "MappingRevision",
    "CommandReceipt", "Conversion", "OrderRequest", "PiAmendment", "Publication",
    "Quote", "RequestLine", "Revision", "AuditEvent", "OutboxEvent"]

