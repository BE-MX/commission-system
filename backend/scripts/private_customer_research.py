"""
私海客户完整背调：按业务员圈定其有效主负责（私海）客户，批量创建 full_research 研究任务，
并导出背调 + 分级结果。

任务创建时会把客户的有效订单与产品明细聚合快照冻结进任务输入，执行研究的 Agent
（openclaw-sales-agent 心跳会自动领取 pending 任务）在上下文中可直接结合下单与产品情况研判。
完成后在"背调中心"（/customer-hub/research）按 T1/T2/T3 档位筛选并人工复核。

执行方式：
  cd backend
  python -m scripts.private_customer_research create --owners zhangsan,lisi [--operator admin] [--limit 50] [--dry-run] [--run-tag TAG]
  python -m scripts.private_customer_research report [--run-tag TAG] [--csv out.csv]
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.sales_automation import private_research_service


CSV_COLUMNS = [
    ("run_tag", "批次标签"),
    ("task_id", "任务ID"),
    ("customer_id", "客户ID"),
    ("customer_code", "客户编码"),
    ("display_name", "客户名称"),
    ("owner_username", "业务员账号"),
    ("owner_name", "业务员"),
    ("tier", "分级"),
    ("match_score", "画像匹配分"),
    ("commercial_value_score", "商业价值分"),
    ("valid_order_count", "有效订单数"),
    ("valid_order_amount_usd", "有效订单金额USD"),
    ("last_order_at", "最近下单时间"),
    ("task_status", "任务状态"),
    ("gate_status", "行业门控"),
    ("result_review_status", "复核状态"),
    ("created_at", "任务创建时间"),
    ("finished_at", "任务完成时间"),
    ("research_summary", "研究摘要"),
]


def cmd_create(args) -> None:
    db = SessionLocal()
    try:
        owners = private_research_service.resolve_owners(db, args.owners.split(","))
        operator_id = None
        if args.operator:
            operator_id = next(iter(private_research_service.resolve_owners(db, [args.operator])))
        run_tag = args.run_tag or f"private-research-{beijing_now():%Y%m%d-%H%M%S}"
        summary = private_research_service.create_private_research_tasks(
            db,
            owner_ids=list(owners),
            run_tag=run_tag,
            operator_id=operator_id,
            limit=args.limit,
            commit=not args.dry_run,
        )
        summary["owners"] = {str(uid): user.real_name for uid, user in owners.items()}
        summary["dry_run"] = args.dry_run
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        if args.dry_run:
            print("dry-run：以上任务未写入数据库。", file=sys.stderr)
    finally:
        db.close()


def cmd_report(args) -> None:
    db = SessionLocal()
    try:
        rows = private_research_service.research_report(db, run_tag=args.run_tag)
    finally:
        db.close()
    output = open(args.csv, "w", newline="", encoding="utf-8-sig") if args.csv else sys.stdout
    try:
        writer = csv.writer(output)
        writer.writerow([label for _, label in CSV_COLUMNS])
        for row in rows:
            writer.writerow([row.get(key) for key, _ in CSV_COLUMNS])
    finally:
        if args.csv:
            output.close()
    print(f"共导出 {len(rows)} 行。", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="私海客户完整背调发起与分级导出")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="为指定业务员的私海客户创建背调任务")
    create.add_argument("--owners", required=True, help="业务员登录用户名或用户ID，逗号分隔")
    create.add_argument("--operator", default=None, help="操作人用户名或ID（写入任务 created_by）")
    create.add_argument("--limit", type=int, default=None, help="最多创建的客户数（按有效订单金额降序截取）")
    create.add_argument("--run-tag", default=None, help="批次标签；缺省按当前时间生成，同批任务据此追踪")
    create.add_argument("--dry-run", action="store_true", help="只打印将要创建的任务，不写入数据库")
    create.set_defaults(func=cmd_create)

    report = subparsers.add_parser("report", help="导出背调与分级结果（CSV）")
    report.add_argument("--run-tag", default=None, help="只导出指定批次；缺省导出全部私海背调任务")
    report.add_argument("--csv", default=None, help="CSV 输出路径；缺省打印到 stdout")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
