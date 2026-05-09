"""
存量数据初始化入口

用法：
  cd backend
  python -m scripts.init_data --dry-run
  python -m scripts.init_data
  python -m scripts.init_data --cutoff-date 2026-04-01
"""

import argparse
import logging
import sys
from datetime import date, datetime

# 确保 app 包可导入
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.services.init_historical_data import run_full_init
from app.system.models import SysDict


# ── 系统字典种子数据 ──────────────────────────────────────

_SYS_DICT_SEED = {
    "props_requirement": [
        {"code": "wig", "label": "假发套", "sort": 1},
        {"code": "mannequin", "label": "模特头", "sort": 2},
        {"code": "accessories", "label": "配饰", "sort": 3},
        {"code": "backdrop", "label": "背景布", "sort": 4},
        {"code": "lighting", "label": "灯光设备", "sort": 5},
        {"code": "prop_stand", "label": "道具架", "sort": 6},
        {"code": "other", "label": "其他", "sort": 99},
    ],
}


def init_sys_dicts(db, dry_run=False):
    """初始化系统字典类型（幂等：已存在则跳过）"""
    logger = logging.getLogger("commission.init")
    created = 0
    skipped = 0

    for dict_type, items in _SYS_DICT_SEED.items():
        for item in items:
            exists = db.query(SysDict).filter(
                SysDict.type == dict_type,
                SysDict.code == item["code"],
            ).first()
            if exists:
                skipped += 1
                continue

            if not dry_run:
                db.add(SysDict(
                    type=dict_type,
                    code=item["code"],
                    label=item["label"],
                    sort=item["sort"],
                    is_active=True,
                ))
            created += 1

    prefix = "[DRY-RUN] " if dry_run else ""
    logger.info(f"{prefix}系统字典: 新建 {created} 条, 跳过 {skipped} 条")
    return created, skipped


def main():
    parser = argparse.ArgumentParser(description="提成系统存量数据初始化")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出计划操作，不实际写入数据库",
    )
    parser.add_argument(
        "--cutoff-date",
        type=str,
        default=None,
        help="历史回款截止日期 (YYYY-MM-DD)，默认当前日期",
    )
    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("commission.init")

    # 解析截止日期
    cutoff = None
    if args.cutoff_date:
        cutoff = datetime.strptime(args.cutoff_date, "%Y-%m-%d").date()
    else:
        cutoff = date.today()

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    logger.info(f"=== 存量数据初始化 ({mode}) ===")
    logger.info(f"截止日期: {cutoff}")

    db = SessionLocal()
    try:
        result = run_full_init(db, cutoff_date=cutoff, dry_run=args.dry_run)

        # 初始化系统字典
        dict_created, dict_skipped = init_sys_dicts(db, dry_run=args.dry_run)

        if not args.dry_run:
            db.commit()
            logger.info("事务已提交")
        else:
            db.rollback()
            logger.info("DRY-RUN 模式，已回滚")

        # 输出汇总
        print("\n" + "=" * 50)
        print(f"初始化结果 ({mode})")
        print("=" * 50)
        print(f"  员工属性记录: {result.employees_synced}")
        print(f"  主管关系记录: {result.supervisors_synced}")
        print(f"  客户快照创建: {result.snapshots_created}")
        print(f"  历史回款同步: {result.payments_synced}")
        print(f"  回款标记已算: {result.payments_marked}")
        print(f"  系统字典新建: {dict_created} (跳过 {dict_skipped})")
        if result.errors:
            print(f"\n  异常 ({len(result.errors)}):")
            for err in result.errors:
                print(f"    - {err}")
        print("=" * 50)

    except Exception as e:
        db.rollback()
        logger.error(f"初始化失败: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
