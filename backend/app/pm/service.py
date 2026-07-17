"""PM Hub 共享 service 辅助：存储锚定、下载签名、审计留痕、通用序列化。

安全红线（设计稿 §7.1/§8）：
- 文件存 REPO_ROOT/backend/data/pm/，绝不放 backend/uploads/（公开静态挂载）
- 下载/预览只走短时效签名 URL；签名消息是版本 id + 过期时间，不含路径，杜绝路径穿越
"""

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.pm.models import PmActivityLog, PmProject, bj_now

logger = logging.getLogger("commission")

# 锚定仓库根（cerebrum 2026-07-03：上传目录必须锚定仓库根，uvicorn CWD 是 backend/）
_REPO_ROOT = Path(__file__).resolve().parents[3]
PM_STORAGE_ROOT = _REPO_ROOT / "backend" / "data" / "pm"

DEFAULT_PROJECT_CODE = "alibaba-ai-agent"


def ensure_storage_root() -> Path:
    PM_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return PM_STORAGE_ROOT


def to_abs(rel_path: str) -> Path:
    """相对存储路径 → 绝对路径。拒绝穿越。"""
    abs_path = (PM_STORAGE_ROOT / rel_path).resolve()
    if not str(abs_path).startswith(str(PM_STORAGE_ROOT.resolve())):
        raise ValueError("非法文件路径")
    return abs_path


# ── 下载/预览签名（照抄素材模块模式：HMAC-SHA256 截断 16 位）───────────────

def _file_sign_secret() -> str:
    settings = get_settings()
    return (settings.PM_TOKEN_SECRET or settings.JWT_SECRET_KEY) + ":pm-file"


def make_file_sign_token(version_id: int, expires: int) -> str:
    msg = f"{version_id}:{expires}"
    return hmac.new(_file_sign_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def build_signed_file_url(version_id: int, disposition: str = "attachment") -> str:
    expires = int(time.time()) + get_settings().PM_FILE_SIGN_TTL_SECONDS
    token = make_file_sign_token(version_id, expires)
    return f"/api/pm/files/{version_id}?token={token}&expires={expires}&disposition={disposition}"


def verify_file_sign(version_id: int, token: str, expires: int) -> bool:
    if not token or int(expires) < int(time.time()):
        return False
    return hmac.compare_digest(token, make_file_sign_token(version_id, int(expires)))


# ── 项目与审计 ────────────────────────────────────────────────────────

def get_default_project(db: Session) -> PmProject:
    project = db.query(PmProject).filter(PmProject.code == DEFAULT_PROJECT_CODE).first()
    if not project:
        project = db.query(PmProject).filter(PmProject.status == "active").first()
    if not project:
        raise ValueError("PM 项目不存在，请先执行 seed 脚本")
    return project


def audit(
    db: Session,
    project_id: int,
    username: str,
    action: str,
    object_type: str,
    object_id: Optional[int] = None,
    object_name: Optional[str] = None,
    detail: Any = None,
) -> None:
    """写审计日志。调用方负责 commit。"""
    db.add(
        PmActivityLog(
            project_id=project_id,
            username=username,
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_name=(object_name or "")[:256],
            detail=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
            created_at=bj_now(),
        )
    )


IMPORTANCE_LABELS = {"required": "必须", "important": "重要", "optional": "锦上添花"}
STATUS_LABELS = {
    "not_started": "未开始",
    "preparing": "准备中",
    "submitted": "已提交",
    "confirmed": "顾问确认",
    "not_required": "无需提供",
}
DELIVERY_LABELS = {"file": "文件", "offline": "线下交付", "link": "外部链接"}
TASK_STATUS_LABELS = {
    "todo": "待办",
    "in_progress": "进行中",
    "done": "已完成",
    "blocked": "受阻",
}
DONE_STATUSES = ("submitted", "confirmed", "not_required")  # 进度口径：视为已完成
