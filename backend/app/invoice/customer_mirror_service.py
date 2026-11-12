"""Narrow, audited writer for customer_info owners during explicit OKKI sync.

Existing records retain other business fields, including external update_time;
the database may automatically maintain its updated_at timestamp.
Absent records receive just the identity, display fields and verified owners;
the ordinary mirror pipeline still fills the rest of the customer profile.
"""

import json

from sqlalchemy import text

from app.invoice import product_service
from app.invoice.customer_sync_models import CustomerSyncLog


class CustomerMirrorSyncError(ValueError):
    pass


def capture(db, company_id, *, lock=False):
    columns = product_service._table_columns(db, "customer_info")
    fields = ["company_name", "country_name", "owner_user_ids"]
    fields.extend(key for key in ("update_time", "updated_at") if key in columns)
    suffix = " FOR UPDATE" if lock and db.get_bind().dialect.name == "mysql" else ""
    row = db.execute(text(
        f"SELECT {', '.join(fields)} FROM `{product_service._schema()}`.customer_info "
        "WHERE company_id=:company_id" + suffix
    ), {"company_id": company_id}).mappings().one_or_none()
    if row is None:
        return None
    # JSON SQL columns arrive as strings from raw SQL; keep numeric/string IDs
    # distinct so an old string array can be repaired for JSON_CONTAINS(number).
    result = dict(row)
    if isinstance(result["owner_user_ids"], str):
        result["owner_user_ids"] = json.loads(result["owner_user_ids"])
    return json.loads(json.dumps(result, default=str))


def apply(db, row, expected, *, operator_id):
    current = capture(db, row.company_id, lock=True)
    if json.dumps(current, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise CustomerMirrorSyncError("客户资料已被其他同步更新，请重新同步")
    remote_time = product_service._parse_ts(row.source_update_time)
    mirror_time = product_service._parse_ts(current.get("update_time")) if current else None
    if mirror_time and (remote_time is None or remote_time < mirror_time):
        raise CustomerMirrorSyncError("OKKI 返回的客户版本早于当前镜像或缺少版本时间，请稍后重新同步")

    owners = [int(value) for value in row.owner_user_ids]
    if (current is not None and isinstance(current["owner_user_ids"], list)
            and all(type(value) is int for value in current["owner_user_ids"])
            and current["owner_user_ids"] == owners):
        return False
    schema = product_service._schema()
    params = {"company_id": row.company_id, "owner_user_ids": json.dumps(owners)}
    if current is None:
        # A competing insert must fail the transaction, never overwrite it.
        db.execute(text(
            f"INSERT INTO `{schema}`.customer_info "
            "(company_id, company_name, country_name, owner_user_ids) "
            "VALUES (:company_id, :company_name, :country_name, :owner_user_ids)"
        ), {**params, "company_name": row.company_name, "country_name": row.country_name})
    else:
        db.execute(text(
            f"UPDATE `{schema}`.customer_info SET owner_user_ids=:owner_user_ids WHERE company_id=:company_id"
        ), params)
    db.add(CustomerSyncLog(
        company_id=row.company_id, created_by=operator_id,
        source_update_time=row.source_update_time, before_data=current,
        after_data=capture(db, row.company_id, lock=True),
    ))
    return True
