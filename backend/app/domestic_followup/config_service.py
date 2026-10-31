"""跟进模块配置：KV 表 + 代码默认值合并。只有 admin 端点调用 update_config。"""
import copy
from datetime import date

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.domestic_followup import visibility
from app.domestic_followup.constants import CONFIG_DEFAULTS
from app.domestic_followup.models import DomesticFollowupConfig


def get_config(db: Session) -> dict:
    config = copy.deepcopy(CONFIG_DEFAULTS)
    for row in db.query(DomesticFollowupConfig).all():
        if row.key in config:
            config[row.key] = row.value
    return config


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)  # True 也是 int，要排除


READ_ALL_PERMISSION = "domestic_followup:read_all"


def _check_urgent_receivers(db: Session, user_ids: list[int]) -> None:
    """紧急推送点开是客户工作台：接收人没有全部范围就看不到别人客户，推送等于白发。"""
    if not user_ids:
        return
    allowed = {row[0] for row in db.execute(
        visibility.holder_ids(READ_ALL_PERMISSION).where(ArkUser.id.in_(user_ids)))}
    missing = [u for u in dict.fromkeys(user_ids) if u not in allowed]
    if not missing:
        return
    first = missing[0]
    user = db.query(ArkUser.real_name, ArkUser.is_active, ArkUser.deleted_at).filter(ArkUser.id == first).first()
    if user is None or user.deleted_at is not None:
        raise ValueError(f"紧急接收人 {first} 不存在")
    if not user.is_active:
        raise ValueError(f"{user.real_name} 已停用，不能做紧急接收人")
    raise ValueError(f"{user.real_name} 没有『全部客户跟进范围』权限，点开推送会看不到客户")


def _validate(db: Session, key: str, value):
    if key == "receipt_delay_days":
        if not _is_int(value) or not 1 <= value <= 30:
            raise ValueError("回访天数需为 1~30 的整数")
    elif key == "urgent_receiver_user_ids":
        if not isinstance(value, list) or not all(_is_int(v) and v > 0 for v in value):
            raise ValueError("紧急接收人需为用户ID列表")
        _check_urgent_receivers(db, value)
    elif key == "fallback_assignee_user_id":
        if value is not None and (not _is_int(value) or value <= 0):
            raise ValueError("兜底负责人需为用户ID")
    elif key == "frequency_days":
        if not isinstance(value, dict) or not all(
            _is_int(v) and 1 <= v <= 365 for v in value.values()
        ):
            raise ValueError("跟进频率需为 {等级: 天数} 且天数 1~365")
    elif key == "receipt_launch_date":
        if value is not None:
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("上线日需为 YYYY-MM-DD") from exc


def update_config(db: Session, changes: dict, user_id: int | None, *, commit: bool = True) -> dict:
    for key, value in changes.items():
        if key not in CONFIG_DEFAULTS:
            raise ValueError(f"未知配置项：{key}")
        _validate(db, key, value)
        row = db.get(DomesticFollowupConfig, key)
        if row is None:
            db.add(DomesticFollowupConfig(key=key, value=value, updated_by=user_id))
        else:
            row.value = value
            row.updated_by = user_id
    db.flush()
    if commit:
        db.commit()
    return get_config(db)
