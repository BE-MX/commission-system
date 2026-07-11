"""售后选择器与列表查询。业务库只读。"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def _limit(value: int) -> int:
    return max(1, min(int(value), 100))


def search_customers(db: Session, keyword: str, limit: int = 20) -> list[dict]:
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(
        text(
            f"SELECT company_id, company_name FROM `{schema}`.customer_info "
            "WHERE company_name LIKE :keyword OR company_id LIKE :keyword "
            "ORDER BY company_name LIMIT :limit"
        ),
        {"keyword": f"%{keyword.strip()}%", "limit": _limit(limit)},
    ).mappings()
    return [
        {"customer_id": str(row["company_id"]), "customer_name": row["company_name"]}
        for row in rows
    ]


def search_orders(
    db: Session,
    customer_id: str,
    keyword: str = "",
    limit: int = 20,
) -> list[dict]:
    customer_id = customer_id.strip()
    if not customer_id:
        raise ValueError("请先选择客户")
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(
        text(
            f"SELECT order_id, order_no, company_id, amount_usd, account_date, status, status_name "
            f"FROM `{schema}`.okki_orders "
            "WHERE company_id = :customer_id "
            "AND (order_no LIKE :keyword OR order_id LIKE :keyword) "
            "ORDER BY account_date DESC LIMIT :limit"
        ),
        {
            "customer_id": customer_id,
            "keyword": f"%{keyword.strip()}%",
            "limit": _limit(limit),
        },
    ).mappings()
    return [
        {
            "order_id": str(row["order_id"]),
            "order_no": str(row["order_no"]),
            "customer_id": str(row["company_id"]),
            "amount_usd": row["amount_usd"],
            "purchase_date": row["account_date"],
            "status": row["status"],
            "status_name": row["status_name"],
        }
        for row in rows
    ]


def search_products(db: Session, keyword: str, limit: int = 20) -> list[dict]:
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(
        text(
            f"SELECT product_id, name, model, color, size, unit "
            f"FROM `{schema}`.okki_products "
            "WHERE COALESCE(disable_flag, 0) = 0 "
            "AND (name LIKE :keyword OR model LIKE :keyword) "
            "ORDER BY name LIMIT :limit"
        ),
        {"keyword": f"%{keyword.strip()}%", "limit": _limit(limit)},
    ).mappings()
    return [
        {
            "product_id": row["product_id"],
            "product_name": row["name"],
            "model": row["model"],
            "color": row["color"],
            "length": row["size"],
            "weight": row["unit"],
        }
        for row in rows
    ]
