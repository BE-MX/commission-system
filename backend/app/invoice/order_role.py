"""Consistent sales-metric exclusion for separately billed presale freight.

The freight receivable is reserved before its remote order is sent. Its unique
expected order name keeps an early OKKI mirror row out of financial statistics
even when OKKI returns a wrong ID or readback fails.
"""
import re


def goods_order_sql(alias: str = "o") -> str:
    """Return a SQL predicate for an OKKI mirror order alias.

    The caller must still apply its existing status, date and ownership scope.
    SQL aliases are implementation constants, never user input.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("Invalid order alias")
    # The OKKI mirror and Ark ledger use different utf8mb4 collations. Casts
    # inherit the session collation, so all cross-schema comparisons
    # must use the ledger column's collation explicitly.
    return f"""NOT EXISTS (
        SELECT 1 FROM ark_receivables freight_role
        WHERE freight_role.kind = 'freight'
          AND (
            freight_role.remote_order_id = CAST({alias}.order_id AS CHAR) COLLATE utf8mb4_unicode_ci
            OR (freight_role.remote_order_name = {alias}.name COLLATE utf8mb4_unicode_ci
                AND freight_role.customer_id = CAST({alias}.company_id AS CHAR) COLLATE utf8mb4_unicode_ci)
          )
    )"""


def goods_receipt_sql(alias: str = "r") -> str:
    """Exclude a freight target's receipt from goods commission import.

    A presale freight receipt is only sent after its target ID has been bound,
    so no name based fallback is needed for this path.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("Invalid receipt alias")
    return f"""NOT EXISTS (
        SELECT 1 FROM ark_receivables freight_role
        WHERE freight_role.kind = 'freight'
          AND freight_role.remote_order_id = CAST({alias}.order_id AS CHAR) COLLATE utf8mb4_unicode_ci
    )"""
