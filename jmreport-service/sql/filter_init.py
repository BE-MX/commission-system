"""
将 jimureport 全量 dump 中的核心表（jimu_* / onl_drag_*）切出来。
丢弃 huiyuan_/rep_demo_/test_/tmp_ 演示数据，避免污染腾讯云生产实例。

输入：sql/jimureport-init.sql  ← 从 jeecgboot/jimureport v2.3.4/db/ 拉的全量 dump
输出：sql/jimureport-core.sql  ← 24 张核心表（16 jimu_* + 8 onl_drag_*）
"""
import re
from pathlib import Path

src = Path(__file__).parent / "jimureport-init.sql"
dst = Path(__file__).parent / "jimureport-core.sql"

KEEP_PREFIXES = ("jimu_", "onl_drag_")


def is_target_table(name: str) -> bool:
    return name.startswith(KEEP_PREFIXES)


def main() -> None:
    if not src.exists():
        raise SystemExit(f"missing {src} — first run:\n"
                         f"  curl -fsSL -o {src} https://raw.githubusercontent.com/jeecgboot/jimureport/v2.3.4/db/jimureport.mysql5.7.create.sql")

    raw = src.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"^-- Table structure for table `(?P<n>[^`]+)`", raw, flags=re.M)

    out = [parts[0]]
    kept, dropped = [], []
    for i in range(1, len(parts), 2):
        name = parts[i]
        body = parts[i + 1]
        if is_target_table(name):
            out.append(f"-- Table structure for table `{name}`")
            out.append(body)
            kept.append(name)
        else:
            dropped.append(name)

    dst.write_text("".join(out), encoding="utf-8")
    print(f"kept {len(kept)} tables: {kept}")
    print(f"dropped {len(dropped)} tables: {dropped}")
    print(f"output: {dst.resolve()}  ({dst.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
