"""素材管理 — 批量操作服务"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from sqlalchemy.orm import Session

from app.asset.models import Asset

# 文件存储根目录
from app.core.config import get_settings

ASSET_STORAGE_ROOT = Path(get_settings().ASSET_STORAGE_ROOT)


def batch_download(
    db: Session,
    asset_ids: list[int],
) -> tuple[bytes, str]:
    """批量打包下载素材。返回 (zip_bytes, zip_filename)。"""
    assets = db.query(Asset).filter(Asset.id.in_(asset_ids), Asset.status != "offline").all()
    if not assets:
        raise ValueError("未找到可下载的素材")

    # 创建临时 ZIP 文件
    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for asset in assets:
                abs_path = ASSET_STORAGE_ROOT / asset.storage_path
                if not abs_path.exists():
                    continue
                # ZIP 内使用原始文件名
                arcname = asset.file_name
                # 处理重名
                counter = 1
                original_arcname = arcname
                while arcname in zf.namelist():
                    name, ext = os.path.splitext(original_arcname)
                    arcname = f"{name}_{counter}{ext}"
                    counter += 1
                zf.write(abs_path, arcname)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        data = f.read()
    os.unlink(tmp_path)

    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    return data, f"leshine_assets_{timestamp}.zip"
