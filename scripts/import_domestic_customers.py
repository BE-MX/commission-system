"""一次性导入《莱莎客户信息录入表》到内贸客户库（与 POST /api/domestic/customers/import 同一 service）。

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe scripts/import_domestic_customers.py <xlsx路径> --operator-id 1 [--dry-run]

--dry-run 只解析和预演归属映射，不写库。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.domestic import customer_import_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="导入莱莎客户信息录入表")
    parser.add_argument("file", help="xlsx 文件路径")
    parser.add_argument("--operator-id", type=int, required=True, help="导入操作人 ark_users.id（记 created_by）")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    file_bytes = Path(args.file).read_bytes()
    rows, skipped, warnings = customer_import_service.parse_workbook(file_bytes)
    by_sheet: dict[str, int] = {}
    for row in rows:
        by_sheet[row["sheet"]] = by_sheet.get(row["sheet"], 0) + 1
    print(f"[import] 有效行 {len(rows)}（{by_sheet}），解析跳过 {len(skipped)}，字段警告 {len(warnings)}")
    for item in skipped[:20]:
        print(f"[skip] {item['sheet']}第{item['row_no']}行 code={item['code']} name={item['shop_name']}：{item['reason']}")
    for item in warnings:
        print(f"[warn] {item['sheet']}第{item['row_no']}行 code={item['code']}：{item['reason']}")

    db = SessionLocal()
    try:
        if args.dry_run:
            from collections import Counter

            from app.auth.models import ArkUser

            active_names = [
                name for (name,) in db.query(ArkUser.real_name).filter(
                    ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)
                )
            ]
            known = set(active_names)
            ambiguous = sorted(n for n, c in Counter(active_names).items() if c > 1)
            unknown = sorted({r["owner_name"] for r in rows if r["owner_name"] and r["owner_name"] not in known})
            print(f"[dry-run] 未识别归属销售: {unknown or '无'}；同名在职用户: {ambiguous or '无'}")
            return
        result = customer_import_service.import_customers(db, rows, args.operator_id)
    finally:
        db.close()
    print(f"[import] 新建 {result['created']}，更新 {result['updated']}，合并同名 {result['merged']}，"
          f"失败 {len(result['errors'])}")
    for item in result["errors"]:
        print(f"[error] {item['row']}：{item['reason']}")
    for item in result["collisions"]:
        print(f"[merge] {item['row']}：{item['reason']}")


if __name__ == "__main__":
    main()
