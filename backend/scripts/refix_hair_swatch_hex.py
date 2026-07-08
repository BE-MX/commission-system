"""数据修复脚本：重提取发色色板图的真实发色 hex（2026-07-08）

背景：早先 upload_hair_color_swatch 直接取 extract_dominant_colors 的最大簇，色板普遍
白底 → 抓到白背景，7 条发色 hex_code 全是 #fcfcfc 类近白，列表色块显示成白点。
规则层已修（service.pick_swatch_hair_hex 跳过近白背景）。本脚本对已有色板图重提取并回填。

范围：仅当前 swatch_path 存在的发色；重提取 hex 与现值不同才更新。幂等（二次运行 updated=0）。

执行：cd backend && python -m scripts.refix_hair_swatch_hex
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.expo import ai_pipeline, service
from app.expo.models import ExpoHairColor


def main():
    from app.color.calc_service import extract_dominant_colors

    db = SessionLocal()
    updated = 0
    try:
        rows = db.query(ExpoHairColor).all()
        print(f"发色总数: {len(rows)}")
        for r in rows:
            if not r.swatch_path:
                print(f"  #{r.id} {r.code}: 无色板图，跳过")
                continue
            path = ai_pipeline.to_abs(r.swatch_path)
            if not path.exists():
                print(f"  #{r.id} {r.code}: 色板文件缺失 {r.swatch_path}，跳过")
                continue
            try:
                dominant = extract_dominant_colors(str(path), k=4)
                new_hex = service.pick_swatch_hair_hex(dominant)
            except Exception as exc:
                print(f"  #{r.id} {r.code}: 提取失败 {exc}，跳过")
                continue
            if not new_hex:
                print(f"  #{r.id} {r.code}: 未提到有效发色，跳过")
                continue
            old_hex = r.hex_code
            if (old_hex or "").upper() == new_hex.upper():
                print(f"  #{r.id} {r.code}: 已是 {old_hex}，无需更新")
                continue
            r.hex_code = new_hex
            updated += 1
            print(f"  #{r.id} {r.code}: {old_hex} -> {new_hex}  [FIXED]")
        db.commit()
        print(f"\n更新完成: {updated} 条 hex_code 已修复")
    except Exception as exc:
        db.rollback()
        print(f"修复失败: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
