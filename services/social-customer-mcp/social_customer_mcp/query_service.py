"""Indexed, parameterized customer lookup queries against lsordertest."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from .config import get_settings
from .models import SocialCustomerRecord, SocialCustomerSearchInput, SocialCustomerSearchResult


def create_db_engine() -> Engine:
    settings = get_settings()
    db_url = settings.db_url.get_secret_value()
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if not db_url.startswith("sqlite"):
        options.update(
            pool_recycle=300,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 5, "read_timeout": 15, "write_timeout": 5},
        )
    return create_engine(db_url, **options)


@contextmanager
def _connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        yield conn


_MATCHED_CTES = {
    "email": """
        matched AS (
            SELECT ci.company_id, CAST(NULL AS UNSIGNED) AS customer_id
            FROM customer_info AS ci
            WHERE ci.email = :lookup

            UNION

            SELECT cc.company_id, cc.customer_id
            FROM customer_contacts AS cc
            WHERE cc.email = :lookup
        )
    """,
    "social_account": """
        matched AS (
            SELECT cc.company_id, cc.customer_id
            FROM customer_contact_socials AS ccs
            JOIN customer_contacts AS cc ON cc.customer_id = ccs.customer_id
            WHERE ccs.value = :lookup
        )
    """,
    "contact_phone": """
        matched AS (
            SELECT cc.company_id, cc.customer_id
            FROM customer_contacts AS cc
            WHERE cc.tel = :lookup
        )
    """,
}

_FALLBACK_MATCHED_CTES = {
    "email": """
        matched AS (
            SELECT ci.company_id, CAST(NULL AS UNSIGNED) AS customer_id
            FROM customer_info AS ci
            WHERE ci.email LIKE '%,%'
              AND FIND_IN_SET(
                  :lookup,
                  REPLACE(LOWER(REGEXP_REPLACE(ci.email, :trim_pattern, '')), ' ', '')
              ) > 0

            UNION

            SELECT ci.company_id, CAST(NULL AS UNSIGNED) AS customer_id
            FROM customer_info AS ci
            WHERE REGEXP_REPLACE(ci.email, :trim_pattern, '') = :lookup

            UNION

            SELECT cc.company_id, cc.customer_id
            FROM customer_contacts AS cc
            WHERE REGEXP_REPLACE(cc.email, :trim_pattern, '') = :lookup
        )
    """,
    "social_account": """
        matched AS (
            SELECT cc.company_id, cc.customer_id
            FROM customer_contact_socials AS ccs
            JOIN customer_contacts AS cc ON cc.customer_id = ccs.customer_id
            WHERE REGEXP_REPLACE(ccs.value, :trim_pattern, '') = :lookup
        )
    """,
    "contact_phone": """
        matched AS (
            SELECT cc.company_id, cc.customer_id
            FROM customer_contacts AS cc
            WHERE REGEXP_REPLACE(cc.tel, :trim_pattern, '') = :lookup
        )
    """,
}

_TRIM_PATTERN = r"^[[:space:]\x{00A0}]+|[[:space:]\x{00A0}]+$"


_DETAIL_SQL = """
WITH
{matched_cte},
matched_companies AS (
    SELECT DISTINCT company_id FROM matched
),
owners AS (
    SELECT
        mc.company_id,
        GROUP_CONCAT(
            DISTINCT COALESCE(NULLIF(ub.full_name, ''), NULLIF(ub.nickname, ''))
            ORDER BY COALESCE(NULLIF(ub.full_name, ''), NULLIF(ub.nickname, ''))
            SEPARATOR ', '
        ) AS owner_user_name
    FROM matched_companies AS mc
    JOIN customer_info AS ci ON ci.company_id = mc.company_id
    LEFT JOIN JSON_TABLE(
        COALESCE(ci.owner_user_ids, JSON_ARRAY()),
        '$[*]' COLUMNS (
            owner_user_id VARCHAR(50)
                CHARACTER SET utf8mb4
                COLLATE utf8mb4_unicode_ci
                PATH '$'
        )
    ) AS owner_ids ON TRUE
    LEFT JOIN user_basic AS ub ON ub.user_id = owner_ids.owner_user_id
    GROUP BY mc.company_id
),
raw_details AS (
    SELECT
        ci.company_id AS _company_id,
        cc.customer_id AS _customer_id,
        ccs.id AS _social_id,
        ci.company_name AS customer_company,
        ci.short_name AS customer_name,
        cc.name AS contact_name,
        ci.email AS customer_email,
        cc.email AS contact_email,
        cc.tel AS contact_phone,
        ccs.platform AS social_platform,
        ccs.value AS social_account,
        COALESCE(NULLIF(owners.owner_user_name, ''), '未进入私海') AS owner_user_name
    FROM matched AS m
    JOIN customer_info AS ci ON ci.company_id = m.company_id
    LEFT JOIN customer_contacts AS cc
        ON cc.company_id = ci.company_id
       AND (m.customer_id IS NULL OR cc.customer_id = m.customer_id)
    LEFT JOIN customer_contact_socials AS ccs ON ccs.customer_id = cc.customer_id
    LEFT JOIN owners ON owners.company_id = ci.company_id
),
details AS (
    SELECT
        MIN(_company_id) AS _company_id,
        MIN(_customer_id) AS _customer_id,
        MIN(_social_id) AS _social_id,
        customer_company,
        customer_name,
        contact_name,
        customer_email,
        contact_email,
        contact_phone,
        social_platform,
        social_account,
        owner_user_name
    FROM raw_details
    GROUP BY
        customer_company, customer_name, contact_name, customer_email,
        contact_email, contact_phone, social_platform, social_account,
        owner_user_name
)
SELECT
    customer_company,
    customer_name,
    contact_name,
    customer_email,
    contact_email,
    contact_phone,
    social_platform,
    social_account,
    owner_user_name,
    COUNT(*) OVER() AS total_count
FROM details
ORDER BY
    customer_company,
    contact_name,
    social_platform,
    social_account,
    _company_id,
    _customer_id,
    _social_id
LIMIT :limit OFFSET :offset
"""


class SocialCustomerQueryService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def search(self, params: SocialCustomerSearchInput) -> SocialCustomerSearchResult:
        matched_by = params.matched_by
        lookup = params.lookup_value.lower() if matched_by == "email" else params.lookup_value
        total_without_page = 0
        with _connection(self.engine) as conn:
            query_params = {
                "lookup": lookup,
                "limit": params.limit,
                "offset": params.offset,
                "trim_pattern": _TRIM_PATTERN,
            }
            sql = text(_DETAIL_SQL.format(matched_cte=_MATCHED_CTES[matched_by]))
            rows = conn.execute(sql, query_params).mappings().all()
            exact_match_exists = bool(rows)
            if not rows and params.offset > 0:
                probe_params = {**query_params, "limit": 1, "offset": 0}
                probe_rows = conn.execute(sql, probe_params).mappings().all()
                if probe_rows:
                    exact_match_exists = True
                    total_without_page = int(probe_rows[0]["total_count"])
            # 源表存在 TAB/NBSP 等首尾脏字符。常见路径先走 B-tree；仅在零命中时
            # 才做正则清理回退，避免每次查询都扫描整表。
            if not exact_match_exists:
                fallback_sql = text(
                    _DETAIL_SQL.format(matched_cte=_FALLBACK_MATCHED_CTES[matched_by])
                )
                rows = conn.execute(fallback_sql, query_params).mappings().all()
                if not rows and params.offset > 0:
                    probe_params = {**query_params, "limit": 1, "offset": 0}
                    probe_rows = conn.execute(fallback_sql, probe_params).mappings().all()
                    if probe_rows:
                        total_without_page = int(probe_rows[0]["total_count"])

        total = int(rows[0]["total_count"]) if rows else total_without_page
        items = [
            SocialCustomerRecord.model_validate(
                {key: value for key, value in row.items() if key != "total_count"}
            )
            for row in rows
        ]
        next_offset = params.offset + len(items) if params.offset + len(items) < total else None
        return SocialCustomerSearchResult(
            matched_by=matched_by,
            total=total,
            count=len(items),
            offset=params.offset,
            has_more=next_offset is not None,
            next_offset=next_offset,
            items=items,
        )
