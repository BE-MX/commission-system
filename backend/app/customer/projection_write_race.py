"""Expected unique-key race recovery for Ark customer projections."""

from __future__ import annotations

from typing import Callable, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


_EXPECTED_UNIQUE_MARKERS = {
    "source_record": (
        "uq_customer_source_record_content",
        "ark_customer_source_records.external_record_key_hash, ark_customer_source_records.content_hash",
    ),
    "conversation": (
        "uq_customer_conversation_external",
        "ark_customer_conversations.source_system, ark_customer_conversations.source_account_key, ark_customer_conversations.external_conversation_id",
    ),
    "message": (
        "uq_customer_message_external",
        "ark_customer_messages.conversation_id, ark_customer_messages.external_message_id",
    ),
    "order": (
        "uq_customer_order_external",
        "ark_customer_orders.source_system, ark_customer_orders.source_account_key, ark_customer_orders.external_order_id",
    ),
    "order_item": (
        "uq_customer_order_item_fingerprint",
        "ark_customer_order_items.order_id, ark_customer_order_items.item_fingerprint",
    ),
}
_T = TypeVar("_T")


def insert_or_load_expected_unique(
    db: Session,
    *,
    entity_type: str,
    insert: Callable[[], _T],
    load_winner: Callable[[], _T | None],
) -> tuple[_T, bool]:
    """Resolve only a known projection unique-key race inside a savepoint."""
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        driver_connection = connection.connection.driver_connection
        if not driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    try:
        with db.begin_nested():
            return insert(), True
    except IntegrityError as exc:
        markers = _EXPECTED_UNIQUE_MARKERS.get(entity_type, ())
        details: list[str] = []
        pending: list[BaseException] = [exc]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            details.append(" ".join(str(value) for value in getattr(current, "args", ())))
            for related in (
                getattr(current, "orig", None),
                current.__cause__,
                current.__context__,
            ):
                if isinstance(related, BaseException):
                    pending.append(related)
        normalized = " ".join(details).casefold()
        if not any(marker.casefold() in normalized for marker in markers):
            raise
        winner = load_winner()
        if winner is None:
            from app.customer.projection_common import ProjectionRetryRequired

            raise ProjectionRetryRequired() from exc
        return winner, False


__all__ = ["insert_or_load_expected_unique"]
