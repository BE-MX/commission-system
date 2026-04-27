"""设计预约 — 工具函数"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def generate_request_no(db: Session) -> str:
    """原子生成申请单号 DSR-YYYYMMDD-XXXX"""
    settings = get_settings()
    prefix = settings.DESIGN_REQUEST_NO_PREFIX
    date_key = date.today().strftime("%Y%m%d")

    db.execute(text(
        "INSERT INTO design_request_seq (date_key, last_seq) VALUES (:dk, 1) "
        "ON DUPLICATE KEY UPDATE last_seq = last_seq + 1"
    ), {"dk": date_key})
    db.flush()

    row = db.execute(text(
        "SELECT last_seq FROM design_request_seq WHERE date_key = :dk"
    ), {"dk": date_key}).fetchone()
    seq = row[0]
    return f"{prefix}-{date_key}-{seq:04d}"


def generate_task_no(db: Session) -> str:
    """原子生成任务编号 DST-YYYYMMDD-XXXX（复用序号表，用 T 前缀的 date_key）"""
    settings = get_settings()
    prefix = settings.DESIGN_TASK_NO_PREFIX
    date_key = "T" + date.today().strftime("%Y%m%d")[:7]  # T + YYYYMMD -> 8 chars

    db.execute(text(
        "INSERT INTO design_request_seq (date_key, last_seq) VALUES (:dk, 1) "
        "ON DUPLICATE KEY UPDATE last_seq = last_seq + 1"
    ), {"dk": date_key})
    db.flush()

    row = db.execute(text(
        "SELECT last_seq FROM design_request_seq WHERE date_key = :dk"
    ), {"dk": date_key}).fetchone()
    seq = row[0]
    today_str = date.today().strftime("%Y%m%d")
    return f"{prefix}-{today_str}-{seq:04d}"
