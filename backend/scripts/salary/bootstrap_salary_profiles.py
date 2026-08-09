# -*- coding: utf-8 -*-
"""薪资档案初始化落库（M1/A3 的写入侧）：3 月三表 + users 表 → ark_salary_employee_profile。

与 `import_from_march.py`（只读分析，产出 HR 复核件）分工：本脚本做**真正的入库**，
并把没有平台账号的发薪员工自动补进 `ark_users`（方舟平台）。

用法：
    python scripts/salary/bootstrap_salary_profiles.py            # dry-run，只打印计划
    python scripts/salary/bootstrap_salary_profiles.py --apply    # 实际写库

落库口径（全部来自设计文档 §2 的实证与 2026-08-06 的 A/B 决策，不是拍脑袋）：

- 底薪一律落 `base_salary_override = 3 月表应发工资**，职级 scheme/code 留空由 HR
  在档案页分批指派。override 优先于职级表——3 月复算必须分位一致，不能靠猜职级。
- 试用期四人（汇总表「请假时间」列的底薪约定文案）：陈佳乐 3500→4000（3/14 转正，
  加权引擎复算 3775）；牟亮亮 30000/40000、王槐竹 6000/6500（3 月整月试用）；
  张桂云例外——她 3 月已按 3500 发放，probation_salary 留空只保留文案，
  否则引擎会按 3000 重算（与真值不符）。
- 保底六人（§2.1 逐人验证过）：刘也/张甜甜/隋晓茹/凯丽比努尔 5000 即生效；
  徐瑞萍/张紫娟 5000 自 2026-04-01 起（3 月不补，负例同样锁死）。
- 特殊计薪两人（§9.5）：姜妮妮 special_calc=1；刘德明 special_calc=1 且
  seniority_override=1000（规则值 200 与真值 1000 对不上，HR 口径钉值）。
- 吕德洋 dept_group_override=业务部：跟单1部 7 人里 6 人归后综部，他是业务总监
  按人挂靠（§4.1 微调 1 的实证案例）。
- 工号撞号三组（§2.5 错误 4，emp_no 有 UNIQUE）：表内靠前者保留原号，后者加
  后缀 A 并写 remark 待 HR 核定——刘德明 293 / 江倩倩 293A，张桂云 319 /
  陈佳乐 319A，吕德洋 3 / 刘美美 3A。
- 江倩倩银行卡与刘德明完全相同（§2.5 错误 2，资金风险级）：**照原样落库**，
  由异常面板的 bank_card_duplicate 拦着等 HR 核真卡号——静默改掉反而毁证据。
- 参保未发薪的 8 人白名单（§2.2）：建 payroll_included=0 的档案（工号编 W01…），
  社保导入时匹配成 not_payroll 而非 unmatched（后者是 blocking 会卡计算门）。
  不建平台账号——他们不在我司发薪，没有登录诉求。

平台账号：按 real_name 匹配 ark_users；缺失的发薪员工自动建号——用户名取姓名拼音
（撞名加数字后缀），初始密码统一 INITIAL_PASSWORD + must_change_password=1，
首次登录强制改密；**不分配角色**（能登录无任何权限，角色由管理员后续指派）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
from decimal import Decimal
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))  # backend/ 供 app.* 导入

from import_from_march import (  # noqa: E402
    DEFAULT_MATERIALS,
    build_profiles,
    detect_non_payroll,
    load_fund,
    load_insurance,
    load_payroll,
    load_platform_users,
    norm_emp_no,
)

INITIAL_PASSWORD = "Lisifa@2026"

# 试用期/保底/特殊计薪等档案级钉值（依据见模块 docstring 逐条注释）
CURATED: dict[str, dict[str, Any]] = {
    "陈佳乐": {"probation_salary": Decimal("3500"), "base_salary_override": Decimal("4000"),
               "regular_date": dt.date(2026, 3, 14),
               "probation_note": "试用期3500底薪，转正后4000底薪"},
    "牟亮亮": {"probation_salary": Decimal("30000"), "base_salary_override": Decimal("40000"),
               "probation_note": "试用期底薪30000，转正底薪40000"},
    "王槐竹": {"probation_salary": Decimal("6000"), "base_salary_override": Decimal("6500"),
               "probation_note": "试用期底薪6000，转正底薪6500"},
    # 张桂云 3 月已按 3500 发放：只留文案，不填 probation_salary（否则引擎按 3000 算）
    "张桂云": {"base_salary_override": Decimal("3500"),
               "probation_note": "试用期3000底薪，转正后3500底薪"},
    "刘也": {"guaranteed_salary": Decimal("5000")},
    "张甜甜": {"guaranteed_salary": Decimal("5000")},
    "隋晓茹": {"guaranteed_salary": Decimal("5000")},
    "凯丽比努尔·阿伍提": {"guaranteed_salary": Decimal("5000")},
    "徐瑞萍": {"guaranteed_salary": Decimal("5000"),
               "guaranteed_from": dt.date(2026, 4, 1)},
    "张紫娟": {"guaranteed_salary": Decimal("5000"),
               "guaranteed_from": dt.date(2026, 4, 1)},
    "姜妮妮": {"special_calc": 1},
    "刘德明": {"special_calc": 1, "seniority_override": Decimal("1000")},
    "吕德洋": {"dept_group_override": "业务部"},
}


def pinyin_username(name: str, taken: set[str]) -> str:
    """姓名 → 全拼用户名（小写、只留字母数字），撞名加 2/3… 后缀。

    非汉字字符（如「凯丽比努尔·阿伍提」的中间点）一律去掉——登录用户名
    不该带标点。
    """
    from pypinyin import lazy_pinyin

    base = "".join(ch for ch in "".join(lazy_pinyin(name)).lower() if ch.isalnum())
    base = base or "user"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}{n}"
        n += 1
    taken.add(candidate)
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="薪资档案初始化落库（默认 dry-run）")
    parser.add_argument("--materials", type=pathlib.Path, default=DEFAULT_MATERIALS)
    parser.add_argument("--apply", action="store_true", help="实际写库（默认只打印计划）")
    args = parser.parse_args()

    from app.core.database import SessionLocal
    from app.salary import service as salary_service
    from app.salary.schemas import ProfileCreate
    from sqlalchemy import text as sa_text

    details, summaries = load_payroll(args.materials / "2026年3月工资表.xls")
    insurance = load_insurance(args.materials / "2026年3月社保&医保明细.xls")
    fund = load_fund(args.materials / "26年3月公积金.xls")
    users = load_platform_users()
    if not users:
        print("[error] 平台 users 表读不到，无法匹配/补建账号", flush=True)
        return 1

    profiles, _ = build_profiles(details, summaries, insurance, fund, users)
    whitelist_rows = detect_non_payroll(profiles, insurance, fund)
    whitelist_names = sorted({a.subject for a in whitelist_rows})
    print(f"解析：发薪 {len(profiles)} 人 / 白名单 {len(whitelist_names)} 人 / "
          f"平台账号 {len(users)} 个", flush=True)

    # 工号撞号：按表内序号靠前者保留原号，后者加 A 后缀 + remark 待核定
    seen_emp: dict[str, int] = {}
    for p in profiles:
        norm = norm_emp_no(p.emp_no)
        seen_emp[norm] = seen_emp.get(norm, 0) + 1
        if seen_emp[norm] > 1:
            p.emp_no = f"{norm}A"
            p.notes.append(f"工号与同人表前行撞号（归一化后同为 {norm}），暂编 {norm}A，待 HR 核定")
        else:
            p.emp_no = norm

    taken_usernames: set[str] = set()
    with SessionLocal() as db:
        taken_usernames = {
            r[0] for r in db.execute(
                sa_text("SELECT username FROM ark_users WHERE deleted_at IS NULL")
            ).fetchall()
        }
        existing_emp = {
            r[0] for r in db.execute(
                sa_text("SELECT emp_no FROM ark_salary_employee_profile")).fetchall()
        }
        existing_id_hash = {
            r[0] for r in db.execute(
                sa_text("SELECT id_card_hash FROM ark_salary_employee_profile "
                        "WHERE id_card_hash IS NOT NULL")).fetchall()
        }

        from app.auth.utils import hash_password
        from app.auth.models import ArkUser
        from app.salary import pii

        created_users: list[tuple[str, str, str]] = []   # (name, username, 初始密码)
        matched_users: list[tuple[str, str]] = []
        created_profiles: list[str] = []
        skipped: list[tuple[str, str]] = []

        def upsert_one(p, *, payroll: bool) -> None:
            if p.emp_no in existing_emp:
                skipped.append((p.name, f"工号 {p.emp_no} 已存在"))
                return
            id_hash = pii.hash_pii(pii.normalize_id_card(p.id_card)) if p.id_card else None
            if id_hash and id_hash in existing_id_hash:
                skipped.append((p.name, "身份证已存在"))
                return

            user_id = p.user_id
            if payroll and user_id is None:
                username = pinyin_username(p.name, taken_usernames)
                if args.apply:
                    user = ArkUser(
                        username=username,
                        password_hash=hash_password(INITIAL_PASSWORD),
                        real_name=p.name,
                        is_active=True,
                        must_change_password=True,
                    )
                    db.add(user)
                    db.flush()
                    user_id = user.id
                created_users.append((p.name, username, INITIAL_PASSWORD))
            elif payroll and user_id is not None:
                matched_users.append((p.name, p.user_login))

            curated = CURATED.get(p.name, {})
            payload = ProfileCreate(
                emp_no=p.emp_no,
                name=p.name,
                user_id=user_id,
                hire_date=p.hire_date,
                dept_detail=p.dept_detail or None,
                position=p.position or None,
                base_salary_override=(
                    curated.get("base_salary_override")
                    if "base_salary_override" in curated
                    else (Decimal(str(p.base_salary_march)) if payroll else None)
                ),
                probation_salary=curated.get("probation_salary"),
                probation_note=curated.get("probation_note"),
                guaranteed_salary=curated.get("guaranteed_salary"),
                guaranteed_from=curated.get("guaranteed_from"),
                guaranteed_to=curated.get("guaranteed_to"),
                regular_date=curated.get("regular_date"),
                dept_group_override=curated.get("dept_group_override"),
                special_calc=curated.get("special_calc", 0),
                seniority_override=curated.get("seniority_override"),
                insurance_entity=p.insurance_entity or None,
                payroll_included=1 if payroll else 0,
                fund_included=1 if p.fund_included else 0,
                id_card=p.id_card or None,
                bank_card=p.bank_card or None,
                remark="；".join(p.notes)[:500] if p.notes else None,
            )
            if args.apply:
                salary_service.create_profile(db, payload)
            created_profiles.append(p.name)
            existing_emp.add(p.emp_no)
            if id_hash:
                existing_id_hash.add(id_hash)

        for p in profiles:
            upsert_one(p, payroll=True)

        # 白名单：参保/缴公积金但不在工资表（detect_non_payroll 已按人去重）
        ins_by_name = {i.name: i for i in insurance}
        fund_by_name = {f.name: f for f in fund}
        for idx, name in enumerate(whitelist_names, start=1):
            ins = ins_by_name.get(name)
            fnd = fund_by_name.get(name)
            src = ins or fnd
            wp = type("WP", (), {})()  # 轻量替身，复用 upsert_one
            wp.emp_no = f"W{idx:02d}"
            wp.name = name
            wp.hire_date = None
            wp.dept_detail = src.dept if src else ""
            wp.position = ""
            wp.base_salary_march = 0.0
            wp.user_id = None
            wp.user_login = ""
            wp.id_card = src.id_card if src else ""
            wp.bank_card = ""
            wp.insurance_entity = src.entity if src else ""
            wp.fund_included = fnd is not None
            wp.notes = [f"参保未发薪（白名单，§2.2）；源表部门={wp.dept_detail or '未知'}"]
            upsert_one(wp, payroll=False)

    print("\n── 计划 ──────────────────────────────", flush=True)
    print(f"档案：新建 {len(created_profiles)}（发薪 {len(profiles)} + 白名单 "
          f"{len(created_profiles) - len(profiles)}），跳过 {len(skipped)}", flush=True)
    for name, why in skipped:
        print(f"  跳过 {name}：{why}", flush=True)
    print(f"平台账号：匹配 {len(matched_users)}，新建 {len(created_users)}", flush=True)
    for name, username, _pwd in created_users:
        print(f"  新建 {name} → {username}", flush=True)
    if created_users:
        print(f"  初始密码统一 {INITIAL_PASSWORD}，首次登录强制改密，无角色", flush=True)

    if not args.apply:
        print("\n[dry-run] 未写库。确认计划无误后加 --apply 执行。", flush=True)
    else:
        print("\n[apply] 已写库。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
