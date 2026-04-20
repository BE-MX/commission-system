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
