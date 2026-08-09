# -*- coding: utf-8 -*-
"""把钉钉绑定从平台账号回填到薪资档案（一次性 + 修复两条链路口径不一）。

背景：用户管理的「绑定钉钉」写 `ark_users.dingtalk_id`，薪资考勤同步读
`ark_salary_employee_profile.dingtalk_userid`——两个字段两条链路，档案初始化时
没有手机号可填，dingtalk_userid 全空，批次页因此全员报「未绑定钉钉」。

回填顺序：
1. 档案挂了平台账号且账号已绑钉钉 → 直接抄（绝大多数）；
2. 档案没账号或账号没绑、但有手机号 → 调钉钉 getbymobile 现查；
3. 剩下的列入清单人工处理（白名单不发薪不同步考勤，不算缺口）。
默认 dry-run，--apply 才写库/打钉钉。
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # backend/


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import text as sa_text

    from app.core.database import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(sa_text(
            "SELECT p.id, p.name, p.mobile, u.dingtalk_id "
            "FROM ark_salary_employee_profile p "
            "LEFT JOIN ark_users u ON p.user_id = u.id "
            "WHERE p.payroll_included = 1 "
            "  AND (p.dingtalk_userid IS NULL OR p.dingtalk_userid = '')"
        )).fetchall()

        from_user: list[tuple[int, str, str]] = []   # profile_id, name, dingtalk_id
        need_api: list[tuple[int, str, str]] = []    # profile_id, name, mobile
        stuck: list[str] = []
        for pid, name, mobile, ud_id in rows:
            if ud_id:
                from_user.append((pid, name, ud_id))
            elif mobile:
                need_api.append((pid, name, mobile))
            else:
                stuck.append(name)

        print(f"待回填 {len(rows)}：账号已绑可直接抄 {len(from_user)}，"
            f"需按手机号现查 {len(need_api)}，无账号无手机号 {len(stuck)} {stuck}")

        api_ok: list[tuple[str, str]] = []
        api_fail: list[str] = []
        if args.apply and need_api:
            from app.dingtalk.client import DingTalkError, get_dingtalk_client
            client = get_dingtalk_client()
            for pid, name, mobile in need_api:
                try:
                    did = await client.get_userid_by_mobile(mobile.strip())
                except DingTalkError as exc:
                    did = None
                    print(f"  [warn] {name} 钉钉接口失败：{exc}")
                if did:
                    db.execute(sa_text(
                        "UPDATE ark_salary_employee_profile SET dingtalk_userid=:d "
                        "WHERE id=:i"), {"d": did, "i": pid})
                    api_ok.append((name, did))
                else:
                    api_fail.append(name)
        if args.apply:
            for pid, _name, did in from_user:
                db.execute(sa_text(
                    "UPDATE ark_salary_employee_profile SET dingtalk_userid=:d "
                    "WHERE id=:i"), {"d": did, "i": pid})
            db.commit()
            bound = db.execute(sa_text(
                "SELECT COUNT(*) FROM ark_salary_employee_profile "
                "WHERE payroll_included=1 AND dingtalk_userid IS NOT NULL "
                "AND dingtalk_userid != ''")).scalar()
            total = db.execute(sa_text(
                "SELECT COUNT(*) FROM ark_salary_employee_profile "
                "WHERE payroll_included=1")).scalar()
            print(f"[apply] 已回填：抄账号 {len(from_user)} + 接口现查 {len(api_ok)}；"
                  f"发薪名单钉钉绑定 {bound}/{total}")
            if api_fail:
                print(f"  接口查不到（手机号与钉钉注册号不一致？）：{'、'.join(api_fail)}")
            if stuck:
                print(f"  无手机号无从查起（补手机号后再跑）：{'、'.join(stuck)}")
        else:
            print("[dry-run] 未写库，加 --apply 执行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
