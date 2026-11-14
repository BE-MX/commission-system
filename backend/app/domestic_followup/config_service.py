"""跟进模块配置：KV 表 + 代码默认值合并。只有 admin 端点调用 update_config。"""
import copy
from datetime import date

from sqlalchemy import select
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
    elif key == "public_sea_follow_launch_date":
        if value is not None:
            try:
                parsed = date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("公海跟进规则生效日需为 YYYY-MM-DD") from exc
            if parsed.isoformat() != value:
                raise ValueError("公海跟进规则生效日需为 YYYY-MM-DD")
            from app.core.time import beijing_today

            saved = db.get(DomesticFollowupConfig, key)
            unchanged = saved is not None and saved.value == value  # 已生效后原样回传不拦，否则其他设置都存不了
            if parsed < beijing_today() and not unchanged:  # 设成过去会让下一次释放一次性放掉一大批客户
                raise ValueError("公海跟进规则生效日不能早于今天")
    elif key == "receipt_launch_date":
        if value is not None:
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("上线日需为 YYYY-MM-DD") from exc
    elif key == "stats_user_ids":
        if not isinstance(value, list) or not all(_is_int(v) and v > 0 for v in value):
            raise ValueError("跟进统计名单需为用户ID列表")
        if len(set(value)) != len(value):
            raise ValueError("跟进统计名单不能重复")
        if value:
            active = set(db.scalars(select(ArkUser.id).where(
                ArkUser.id.in_(value), ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))))
            if active != set(value):
                raise ValueError("跟进统计名单包含不存在或已停用的用户")
    elif key == "stats_non_workdays":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("非工作日需为日期字符串列表")
        if len(set(value)) != len(value):
            raise ValueError("非工作日需为不重复的日期列表")
        try:
            parsed = [date.fromisoformat(v) for v in value]
        except (TypeError, ValueError) as exc:
            raise ValueError("非工作日需为 YYYY-MM-DD 列表") from exc
        if any(day.isoformat() != raw for day, raw in zip(parsed, value)):
            raise ValueError("非工作日需为 YYYY-MM-DD 列表")
        if len(parsed) > 366:
            raise ValueError("非工作日最多维护 366 天")
    elif key == "insight_generation_enabled" and not isinstance(value, bool):
        raise ValueError("AI 生成开关需为布尔值")


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
