# -*- coding: utf-8 -*-
"""按钉钉通讯录回填平台用户手机号（一次性运维脚本）。

- 只填**缺失**的手机号（phone 为 NULL/空串），已存在的一律不动；
- 手机号只保留 11 位：去非数字字符，带 86 国家码（13 位）取后 11 位；
- 通讯录姓名带英文后缀（"代晴玉 Daisy"）→ 只取中文部分匹配 real_name；
- 顺带回填薪资档案的 mobile（同样只填空的）——考勤钉钉绑定按手机号反查要用。
默认 dry-run，--apply 才写库。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # backend/

import openpyxl  # noqa: E402


# 通讯录用短名、平台用全名的对照（匹配键 = 平台 real_name → 通讯录姓名）
NAME_ALIAS = {
    "凯丽比努尔·阿伍提": "凯丽比努尔",
}


def norm_mobile(v) -> str:
    """+86-15621190058 / 156 2119 0058 → 15621190058。凑不齐 11 位返回 ''。"""
    digits = re.sub(r"\D", "", str(v or ""))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits if len(digits) == 11 and digits.startswith("1") else ""


def cn_name(v) -> str:
    """通讯录姓名去英文后缀：'代晴玉 Daisy' → '代晴玉'。"""
    s = str(v or "").strip()
    m = re.match(r"^([一-龥·]+)", s)
    return m.group(1) if m else s


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.file, read_only=True)
    ws = wb.worksheets[0]
    contacts: dict[str, str] = {}
    bad_rows: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        name = cn_name(row[0])
        mobile = norm_mobile(row[1] if len(row) > 1 else None)
        if not name:
            continue
        if not mobile:
            bad_rows.append(f"{name}({row[1]})")
            continue
        contacts[name] = mobile
    print(f"通讯录解析：{len(contacts)} 人有效，{len(bad_rows)} 行手机号无效 {bad_rows}")

    from app.core.database import SessionLocal
    from sqlalchemy import text as sa_text

    with SessionLocal() as db:
        users = db.execute(
            sa_text("SELECT id, real_name, phone FROM ark_users "
                    "WHERE is_active=1 AND deleted_at IS NULL")
        ).fetchall()
        fill: list[tuple[int, str, str]] = []
        already: list[str] = []
        no_contact: list[str] = []
        for uid, real_name, phone in users:
            if phone and str(phone).strip():
                already.append(real_name)
                continue
            mob = contacts.get((real_name or "").strip())
            if not mob:
                mob = contacts.get(NAME_ALIAS.get((real_name or "").strip(), ""))
            if mob:
                fill.append((uid, real_name, mob))
            else:
                no_contact.append(real_name)

        print(f"平台用户：已有手机号 {len(already)}，将回填 {len(fill)}，通讯录查无此人 {len(no_contact)}")
        for _uid, name, mob in fill:
            print(f"  回填 {name} → {mob}")
        if no_contact:
            print("  查无此人：" + "、".join(no_contact))

        # 通讯录里多出来的人（不是平台在职用户）
        user_names = {r[1] for r in users}
        extra = sorted(set(contacts) - user_names)
        if extra:
            print(f"通讯录中非在职平台用户 {len(extra)} 人：{'、'.join(extra)}")

        if args.apply:
            for uid, _name, mob in fill:
                db.execute(sa_text(
                    "UPDATE ark_users SET phone=:m, updated_at=NOW() WHERE id=:i"
                ), {"m": mob, "i": uid})
            n_prof = db.execute(sa_text(
                "UPDATE ark_salary_employee_profile p JOIN ark_users u ON p.user_id = u.id "
                "SET p.mobile = u.phone "
                "WHERE (p.mobile IS NULL OR p.mobile = '') AND u.phone IS NOT NULL AND u.phone != ''"
            )).rowcount
            db.commit()
            print(f"[apply] 已回填用户 {len(fill)} 人；薪资档案 mobile 同步 {n_prof} 行")
        else:
            print("[dry-run] 未写库，加 --apply 执行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
