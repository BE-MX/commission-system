"""清空素材库所有标签维度、标签值和素材标签关联

用法：在 backend/ 目录下执行
  python scripts/clear_asset_tags.py
"""

import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from app.core.database import SessionLocal


def clear_all():
    db = SessionLocal()
    try:
        # 按外键依赖顺序删除
        db.execute(text("DELETE FROM ark_asset_tags"))
        db.execute(text("DELETE FROM ark_tag_values"))
        db.execute(text("DELETE FROM ark_tag_dimensions"))
        db.commit()
        print("[OK] 已清空：ark_asset_tags / ark_tag_values / ark_tag_dimensions")
        print("     现在可以前往「系统管理 → 标签维度管理」重新手动创建维度。")
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] 出错: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        clear_all()
    else:
        confirm = input("确认清空所有标签维度和标签值？此操作不可恢复 [yes/no]: ")
        if confirm.strip().lower() == "yes":
            clear_all()
        else:
            print("已取消")
