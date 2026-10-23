"""模块配置存取：单行 JSON，缺省值兜底，非法内容拒绝静默生效。"""
import json
import logging
from copy import deepcopy

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.perf_goal.models import METRICS, PerfGoalConfig

logger = logging.getLogger(__name__)

CONFIG_KEY = "main"

DEFAULT_CONFIG = {
    "metrics_enabled": {metric: True for metric in METRICS},
    "delivery_channel_mode": "worknotice_first",
    "ai_preset": "perf_report_analyst",
    "default_factor": "1.0",
    "order_decisions": [],
}


def load_config(db: Session) -> dict:
    row = db.get(PerfGoalConfig, CONFIG_KEY)
    config = deepcopy(DEFAULT_CONFIG)
    if row is not None and isinstance(row.payload, dict):
        for key, value in row.payload.items():
            if key == "metrics_enabled" and isinstance(value, dict):
                config["metrics_enabled"].update({m: bool(value.get(m, True)) for m in METRICS})
            elif key in config:
                config[key] = value
    return config


def save_config(db: Session, update, operator_id: int) -> dict:
    row = db.get(PerfGoalConfig, CONFIG_KEY)
    if row is None:
        row = PerfGoalConfig(key=CONFIG_KEY, payload=deepcopy(DEFAULT_CONFIG))
        db.add(row)
        db.flush()
    payload = deepcopy(row.payload) if isinstance(row.payload, dict) else deepcopy(DEFAULT_CONFIG)
    # JSON 模式序列化：Decimal→字符串、date→ISO、嵌套模型→dict，保证落库即为 JSON 安全结构
    changes = json.loads(update.model_dump_json(exclude_unset=True))
    for key, value in changes.items():
        if key == "metrics_enabled":
            enabled = dict(payload.get("metrics_enabled") or DEFAULT_CONFIG["metrics_enabled"])
            enabled.update({metric: bool(flag) for metric, flag in value.items()})
            payload[key] = enabled
        else:
            payload[key] = value
    row.payload = payload
    row.updated_by = operator_id
    row.updated_at = beijing_now()
    db.commit()
    return load_config(db)


def order_decision_rules(db: Session) -> dict:
    """Shape accepted by battle_report order_decisions.decision_index."""
    return {"order_decisions": load_config(db).get("order_decisions") or []}
