"""Verify the deployed MCP protocol and query behavior without printing customer PII."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from dotenv import load_dotenv
from sqlalchemy import text

from social_customer_mcp.config import get_settings
from social_customer_mcp.query_service import _MATCHED_CTES, create_db_engine


REQUIRED_ITEM_FIELDS = {
    "customer_company",
    "customer_name",
    "contact_name",
    "customer_email",
    "contact_email",
    "contact_phone",
    "social_platform",
    "social_account",
    "owner_user_name",
}


def _sample_lookups():
    engine = create_db_engine()
    try:
        with engine.connect() as conn:
            samples = {
                "email": conn.execute(
                    text(
                        "SELECT email FROM customer_info "
                        "WHERE email IS NOT NULL AND email <> '' AND email NOT LIKE '%,%' LIMIT 1"
                    )
                ).scalar_one(),
                "social_account": conn.execute(
                    text(
                        "SELECT value FROM customer_contact_socials "
                        "WHERE value IS NOT NULL AND value <> '' "
                        "GROUP BY customer_id, platform, value HAVING COUNT(*) > 1 LIMIT 1"
                    )
                ).scalar_one(),
                "contact_phone": conn.execute(
                    text(
                        "SELECT tel FROM customer_contacts "
                        "WHERE tel IS NOT NULL AND tel <> '' LIMIT 1"
                    )
                ).scalar_one(),
            }
            for matched_by, lookup in samples.items():
                plan_rows = conn.execute(
                    text(f"EXPLAIN WITH {_MATCHED_CTES[matched_by]} SELECT * FROM matched"),
                    {"lookup": lookup},
                ).mappings().all()
                base_table_rows = [
                    row for row in plan_rows if not str(row["table"]).startswith("<")
                ]
                if not base_table_rows or any(
                    row["type"] == "ALL" or not row["key"] for row in base_table_rows
                ):
                    raise RuntimeError(f"{matched_by} exact-match plan is not fully indexed")
            return samples
    finally:
        engine.dispose()


async def _collect(session: ClientSession, matched_by: str, lookup: str):
    offset = 0
    items = []
    total = None
    while True:
        result = await session.call_tool(
            "social_customer_search",
            {"params": {matched_by: lookup, "limit": 50, "offset": offset}},
        )
        if result.isError or not result.structuredContent:
            raise RuntimeError(f"{matched_by} MCP verification failed")
        payload = result.structuredContent
        if payload["matched_by"] != matched_by or payload["count"] != len(payload["items"]):
            raise RuntimeError(f"{matched_by} response metadata is inconsistent")
        if total is None:
            total = payload["total"]
        elif total != payload["total"]:
            raise RuntimeError(f"{matched_by} total changed while paging")
        for item in payload["items"]:
            if set(item) != REQUIRED_ITEM_FIELDS or not item["owner_user_name"]:
                raise RuntimeError(f"{matched_by} response fields are invalid")
        items.extend(payload["items"])
        if not payload["has_more"]:
            break
        offset = payload["next_offset"]
    if not items or total != len(items):
        raise RuntimeError(f"{matched_by} result count is inconsistent")
    return items


async def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    settings = get_settings()
    endpoint = os.getenv(
        "SOCIAL_CUSTOMER_MCP_ENDPOINT",
        "https://leshine.work/mcp/social-customer/",
    )
    headers = {"Authorization": f"Bearer {settings.token.get_secret_value()}"}
    samples = _sample_lookups()
    summary = {}

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        async with streamable_http_client(endpoint, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
                if [tool.name for tool in tools.tools] != ["social_customer_search"]:
                    raise RuntimeError("unexpected MCP tool list")
                for matched_by, lookup in samples.items():
                    first = await _collect(session, matched_by, lookup)
                    second = await _collect(session, matched_by, lookup)
                    serialized_first = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in first]
                    serialized_second = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in second]
                    if serialized_first != serialized_second:
                        raise RuntimeError(f"{matched_by} pagination order is unstable")
                    if len(serialized_first) != len(set(serialized_first)):
                        raise RuntimeError(f"{matched_by} returned duplicate public rows")
                    summary[matched_by] = {"ok": True, "count": len(first)}

    print(json.dumps({"status": "ok", "checks": summary}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
