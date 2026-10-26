"""2026 年度绩效目标种子（GMV + 新签，真实数据内嵌于 app/perf_goal/seed.py）。

执行方式（在 backend 目录、数据库已迁移到 202_perf_goals 后）：
  python -m scripts.perf_goal_seed_2026            # dry-run，只打印计划与警告
  python -m scripts.perf_goal_seed_2026 --apply    # 实际写入；幂等，重复运行不重复写入
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.perf_goal.seed import run_seed


def main() -> int:
    apply = "--apply" in sys.argv
    with SessionLocal() as db:
        summary = run_seed(db, apply=apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] period_id={summary['period_id']} period_created={summary['period_created']}")
    print(f"[{mode}] users_planned={summary['users_planned']} goals_written={summary['goals_written']} "
          f"team_rows_written={summary['team_rows_written']}")
    for warning in summary["warnings"]:
        print(f"[WARN] {warning}")
    if not apply:
        print("加 --apply 实际写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
