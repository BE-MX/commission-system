"""薪资模块 — 异常面板 v1（M2-e）。

## 这个模块存在的理由

到 M2 结束时，一个批次的数据来自四个互不相识的来源：钉钉考勤、社保 Excel、
公积金 Excel、员工档案。**它们出问题的方式全都是静默的**——社保没匹配上不会报错，
只会让那个人的减项变成 0；考勤没同步不会报错，只会让缺勤扣款变成 0。
钱只会算多，不会算少，而多发的钱没有人会来投诉。

所以这里不做「校验」，做**待办清单**：把「还差什么」聚合成一屏能看完的列表，
每条都带 employee_id 让前端能点进去定位（设计文档 §7.2「点击定位到行」）。

## 两个原则

1. **每条异常都要给下一步动作**，不能只报告现象。「张三未匹配社保」是现象，
   「张三未匹配社保 → 去社保 Excel 核对身份证，或在档案里确认他不参保」才是待办。
   （交互设计原则：反馈引导行动）

2. **blocking 与 info 必须分开计数。** blocking 是「这么算出来的钱是错的」，
   info 是「你可能想看一眼」。混在一起的话，8 条正常的白名单提示会把 1 条
   真正致命的未匹配淹掉——而 HR 只会看列表长度决定要不要继续。

## 不在 v1 范围内的

保底触发、月中调薪加权、auto 被人工覆盖但 auto 已变（设计文档 §7.2 提到的后三类）
都依赖 `ark_salary_record`，那张表要 M3 算完才有数据。v1 只覆盖「进计算之前」
就能查出来的问题：设计文档 §8 M2 的四类（未匹配社保 / 参保白名单 / 迟到明细 /
钉钉未绑定），外加档案自身的三类致命项（身份证重复 / 银行卡重复 / 定薪缺失）。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.salary.models import (
    SalaryAttendance,
    SalaryEmployeeProfile,
    SalaryFundImport,
    SalaryInsuranceImport,
    SalaryPeriod,
)

logger = logging.getLogger("commission")

# 严重度。blocking 决定「能不能进计算」，info 只是让人看一眼。
BLOCKING = "blocking"
INFO = "info"

# 异常类型。前端按 kind 分组、配图标与跳转目标，所以这些字符串是**契约**，
# 改名等于改接口——要改先改前端。
KIND_DINGTALK_UNBOUND = "dingtalk_unbound"
KIND_DINGTALK_DUPLICATE = "dingtalk_duplicate"
KIND_ATTENDANCE_MISSING = "attendance_missing"
KIND_ATTENDANCE_PENDING = "attendance_pending_manual"
KIND_ATTENDANCE_ABNORMAL = "attendance_abnormal"
KIND_INSURANCE_UNMATCHED = "insurance_unmatched"
KIND_INSURANCE_MISSING = "insurance_missing"
KIND_INSURANCE_WHITELIST = "insurance_whitelist"
KIND_FUND_UNMATCHED = "fund_unmatched"
KIND_FUND_MISSING = "fund_missing"
KIND_IMPORT_DUPLICATE = "import_duplicate"
KIND_BANK_CARD_DUPLICATE = "bank_card_duplicate"
KIND_BASE_SALARY_MISSING = "base_salary_missing"
# 记录级（M3，计算后才查得出）。negative_net 拦的是 confirm 不是 calculate——
# 必须先算出负数才知道它存在，所以它不该进 ready_to_calculate 的分母。
KIND_NEGATIVE_NET = "negative_net"
KIND_GUARANTEED_TOPUP = "guaranteed_topup"
KIND_MID_MONTH_WEIGHTED = "mid_month_weighted"
KIND_MANUAL_OVERRIDE = "manual_override_diff"

KIND_LABELS = {
    KIND_DINGTALK_UNBOUND: "未绑定钉钉",
    KIND_DINGTALK_DUPLICATE: "钉钉 userid 撞号",
    KIND_ATTENDANCE_MISSING: "考勤缺失",
    KIND_ATTENDANCE_PENDING: "请假小时未录",
    KIND_ATTENDANCE_ABNORMAL: "考勤异常明细",
    KIND_INSURANCE_UNMATCHED: "社保未匹配到档案",
    KIND_INSURANCE_MISSING: "应参保但无社保数据",
    KIND_INSURANCE_WHITELIST: "参保未发薪（白名单）",
    KIND_FUND_UNMATCHED: "公积金未匹配到档案",
    KIND_FUND_MISSING: "应缴公积金但无数据",
    KIND_IMPORT_DUPLICATE: "导入表身份证重复",
    KIND_BANK_CARD_DUPLICATE: "银行卡重复",
    KIND_BASE_SALARY_MISSING: "无法确定底薪",
    KIND_NEGATIVE_NET: "实发为负",
    KIND_GUARANTEED_TOPUP: "保底补足已触发",
    KIND_MID_MONTH_WEIGHTED: "月中调薪/转正加权",
    KIND_MANUAL_OVERRIDE: "人工覆盖与引擎值不一致",
}

# 进计算之前就能查的 kind（ready_to_calculate 的分母）。记录级 kind 不在其中。
_PRE_CALC_KINDS = frozenset({
    KIND_DINGTALK_UNBOUND, KIND_DINGTALK_DUPLICATE, KIND_ATTENDANCE_MISSING,
    KIND_ATTENDANCE_PENDING, KIND_INSURANCE_UNMATCHED, KIND_INSURANCE_MISSING,
    KIND_FUND_UNMATCHED, KIND_FUND_MISSING, KIND_IMPORT_DUPLICATE,
    KIND_BANK_CARD_DUPLICATE, KIND_BASE_SALARY_MISSING,
})


def _item(
    kind: str,
    severity: str,
    message: str,
    action: str,
    *,
    employee_id: Optional[int] = None,
    emp_no: Optional[str] = None,
    name: Optional[str] = None,
    ref: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """一条异常。

    `employee_id` 是前端定位到明细行的键，`ref` 放来源行 id（未匹配的导入行
    没有 employee_id，只能靠 ref 打开导入明细）。两个都给不出的异常没法处理，
    就不该出现在待办清单里。
    """
    return {
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "severity": severity,
        "employee_id": employee_id,
        "emp_no": emp_no,
        "name": name,
        "message": message,
        "action": action,
        "ref": ref or {},
    }


def _payroll_profiles(db: Session) -> list[SalaryEmployeeProfile]:
    """发薪名单：在职 + payroll_included。

    离职的人不在这里——他们的末月工资由 M3 按离职日期单独处理，
    如果混进来会让「考勤缺失」刷出一堆早就走了的人，把真待办淹掉。

    实现委托给 `attendance_service.payroll_profiles`：同步按 A 取人、异常面板按 B
    数分母，两份筛选条件迟早会漂，而漂的那次就是「某人没同步上但面板不报警」。
    """
    from app.salary import attendance_service
    return attendance_service.payroll_profiles(db)


# ---------------------------------------------------------------------------
# 各类检查
# ---------------------------------------------------------------------------

def check_attendance(db: Session, period: SalaryPeriod,
                     profiles: list[SalaryEmployeeProfile]) -> list[dict[str, Any]]:
    """考勤三类：没绑钉钉 / 没考勤行 / 请假小时没录 + 一类明细提示。"""
    rows = {
        r.employee_id: r
        for r in db.query(SalaryAttendance)
        .filter(SalaryAttendance.period_id == period.id).all()
    }
    out: list[dict[str, Any]] = []

    # userid 撞号：同步会整批拒绝（attendance_service 里说明了为什么必须拒），
    # 但面板得在 HR 点同步之前就告诉他，而不是让他点完等一分钟再看报错。
    by_uid: dict[str, list[SalaryEmployeeProfile]] = defaultdict(list)
    for p in profiles:
        uid = (p.dingtalk_userid or "").strip()
        if uid:
            by_uid[uid].append(p)
    dup_ids: set[int] = set()
    for uid, dupes in by_uid.items():
        if len(dupes) < 2:
            continue
        dup_ids.update(d.id for d in dupes)
        # **一组撞号出一条，不是一人一条。** 撞号是「这两个人共用一个号」这一件事，
        # 报两遍会让 10 组撞号刷出 20 条 blocking，把真正待办（比如那一个未绑定的人）
        # 按字母序压到清单末尾。当事人自己不进「与…共用」，否则读起来像自己跟自己撞。
        # 写法照 KIND_BANK_CARD_DUPLICATE：employee_id 给第一个，其余进 ref.peers。
        head, *peers = dupes
        names = "、".join(d.name for d in peers)
        out.append(_item(
            KIND_DINGTALK_DUPLICATE, BLOCKING,
            f"{head.name} 与 {names} 共用同一个钉钉 userid（{uid}）",
            "同一个 userid 只能绑一个人，否则同步时其中一人考勤会是空的。"
            "请到员工档案里改成各自真实的 userid",
            employee_id=head.id, emp_no=head.emp_no, name=head.name,
            ref={
                "dingtalk_userid": uid,
                "peers": [{"employee_id": d.id, "emp_no": d.emp_no, "name": d.name}
                          for d in peers],
            },
        ))

    for p in profiles:
        row = rows.get(p.id)
        # 撞号的人必然还没考勤行（同步被整批拒了），再各报一条「考勤缺失」是
        # 同一件事说两遍——先把撞号改对，考勤缺失自然消失。
        if p.id in dup_ids and row is None:
            continue
        if not (p.dingtalk_userid or "").strip():
            # 手工录入已齐（请假小时都录了）的未绑定人降为提示：数据缺口已被
            # 人工补上，考勤同步本来就覆盖不到他（姜妮妮/刘德明这类不打卡人员）。
            # 还按 blocking 报的话，这批人永远卡住计算门——2026-08-07 实测。
            manual_done = (
                row is not None
                and row.personal_leave_hours is not None
                and row.sick_leave_hours is not None
            )
            if manual_done:
                out.append(_item(
                    KIND_DINGTALK_UNBOUND, INFO,
                    f"{p.name} 未绑定钉钉 userid，本月考勤为手工录入",
                    "数据已齐，可继续；长期建议补手机号后回填绑定（不打卡人员可忽略）",
                    employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ))
            else:
                out.append(_item(
                    KIND_DINGTALK_UNBOUND, BLOCKING,
                    f"{p.name} 未绑定钉钉 userid，考勤永远拉不到",
                    "在员工档案里补钉钉 userid 后重新同步；确实不打卡的人请手工录入考勤",
                    employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ))
            # 没绑定就必然没考勤行，再报一条「考勤缺失」是同一件事说两遍
            continue
        if row is None:
            out.append(_item(
                KIND_ATTENDANCE_MISSING, BLOCKING,
                f"{p.name} 本月没有考勤记录",
                "重新同步考勤；若钉钉侧确实无记录（如全月请假），请手工录入",
                employee_id=p.id, emp_no=p.emp_no, name=p.name,
            ))
            continue

        # 请假小时钉钉取不到，只能人工录。NULL 不是 0——当 0 处理会让实出天数
        # 按满勤算，还白发 100 元全勤奖。
        pending = [f for f in ("personal_leave_hours", "sick_leave_hours")
                   if getattr(row, f, None) is None]
        if pending:
            miss = "事假" if "personal_leave_hours" in pending else ""
            miss += "、" if len(pending) == 2 else ""
            miss += "病假" if "sick_leave_hours" in pending else ""
            out.append(_item(
                KIND_ATTENDANCE_PENDING, BLOCKING,
                f"{p.name} 的{miss}小时还没录（钉钉取不到这几列）",
                "在考勤页填写；没有请假就填 0，留空会被当成「未录入」而不是「无请假」",
                employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ref={"attendance_id": row.id, "fields": pending},
            ))

        # 明细提示：迟到/早退/漏打卡/旷工。这些不阻断计算（金额算得出来），
        # 但 100 元全勤奖是靠它判的，HR 要能在发薪前扫一眼有没有明显不对。
        marks = []
        for field, label in (("late_count", "迟到"), ("early_leave_count", "早退"),
                             ("miss_punch_count", "漏打卡"), ("absent_count", "旷工")):
            val = getattr(row, field, None)
            if val and Decimal(str(val)) > 0:
                marks.append(f"{label} {val}")
        if marks:
            out.append(_item(
                KIND_ATTENDANCE_ABNORMAL, INFO,
                f"{p.name}：{'，'.join(marks)}",
                "核对无误即可忽略；有争议在考勤页直接改，全勤奖会跟着重判",
                employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ref={"attendance_id": row.id},
            ))
    return out


def _check_import(
    db: Session, period: SalaryPeriod, profiles: list[SalaryEmployeeProfile],
    model, *, kind_unmatched: str, kind_missing: str,
    kind_whitelist: Optional[str], source_label: str,
    required: dict[int, bool],
) -> list[dict[str, Any]]:
    """社保与公积金的检查逻辑完全同构，只有表名和文案不同。

    **写成一个函数而不是抄两遍**：这两条链路的判定口径必须永远一致，
    抄两遍的话下次只改一处，另一处静默走偏——而走偏的表现是某些人减项为 0，
    不会报任何错。
    """
    rows = db.query(model).filter(model.period_id == period.id).all()
    matched_ids = {r.employee_id for r in rows if r.employee_id is not None}
    out: list[dict[str, Any]] = []

    for r in rows:
        if r.match_status == "duplicate":
            # **这一条今天就在少扣钱。** import_persist 把同一个 id_card_hash 的
            # 第二行判成「誊写错误」并整行剔出计算（personal_total 不进减项）。
            # 但补缴、跨主体参保都会让一个人合法地出现两行——3 月社保表就有
            # 缴费类型「正常缴费/补缴」这一列。被剔掉的那几百块没人扣，
            # 而工资表上完全看不出来。
            out.append(_item(
                KIND_IMPORT_DUPLICATE, BLOCKING,
                f"{source_label}表里「{r.name or '（无姓名）'}」的身份证与另一行重复，"
                f"这一行已被排除在计算之外",
                f"看是誊写错误还是补缴/跨主体多行：誊写错误改{source_label} Excel 重导；"
                f"确实该合并计入的，两行金额相加后合成一行再导",
                employee_id=r.employee_id, name=r.name,
                ref={"row_id": r.id, "source": source_label,
                     "personal_amount": str(
                         getattr(r, "personal_total", None)
                         or getattr(r, "personal_amount", None) or "0")},
            ))
        elif r.employee_id is None or r.match_status == "unmatched":
            out.append(_item(
                kind_unmatched, BLOCKING,
                f"{source_label}表里的「{r.name or '（无姓名）'}」没有匹配到员工档案",
                f"核对身份证号是否录错；确认此人不发薪的话，"
                f"在档案里建档并标记「仅参保」，这条就会转成白名单提示",
                name=r.name,
                ref={"row_id": r.id, "source": source_label},
            ))
        elif kind_whitelist and r.match_status == "not_payroll":
            # 白名单是**预期内**的（参保但不在本公司发薪），不阻断。
            # 但必须列出来：万一某个人是被误标成「仅参保」，他这个月就一分钱没有，
            # 而系统全程不会报错。
            out.append(_item(
                kind_whitelist, INFO,
                f"{r.name} 参保但不发薪（白名单）",
                "确认此人本月确实不在发薪名单内；若应发薪，改档案的「参与发薪」开关",
                employee_id=r.employee_id, name=r.name,
                ref={"row_id": r.id, "source": source_label},
            ))

    if rows:
        # 一行都没导入时不报「缺失」——那是「还没导入」，不是「导入了但少人」。
        # 前者是流程还没走到，报出来只会让面板在流程第一步就红一片。
        for p in profiles:
            if not required.get(p.id, False):
                continue
            if p.id not in matched_ids:
                out.append(_item(
                    kind_missing, BLOCKING,
                    f"{p.name} 应缴{source_label}，但导入表里没有他",
                    f"核对{source_label} Excel 是否漏了这个人；"
                    f"确实本月不缴的话，改档案对应开关",
                    employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ))
    return out


def check_insurance(db, period, profiles):
    # 参保主体为空 = 这个人不参保，不该被要求有社保行
    required = {p.id: bool((p.insurance_entity or "").strip()) for p in profiles}
    return _check_import(
        db, period, profiles, SalaryInsuranceImport,
        kind_unmatched=KIND_INSURANCE_UNMATCHED,
        kind_missing=KIND_INSURANCE_MISSING,
        kind_whitelist=KIND_INSURANCE_WHITELIST,
        source_label="社保", required=required,
    )


def check_fund(db, period, profiles):
    required = {p.id: bool(p.fund_included) for p in profiles}
    return _check_import(
        db, period, profiles, SalaryFundImport,
        kind_unmatched=KIND_FUND_UNMATCHED,
        kind_missing=KIND_FUND_MISSING,
        # 公积金没有「参保未发薪」概念（不发薪的人本来就不在公积金表里），
        # 硬套一个白名单类型只会造出一堆看不懂的提示
        kind_whitelist=None,
        source_label="公积金", required=required,
    )


def check_profiles(db: Session,
                   profiles: list[SalaryEmployeeProfile]) -> list[dict[str, Any]]:
    """档案自身的致命项：银行卡撞号与定薪缺失。

    **这里不查身份证重复**：`ark_salary_employee_profile.id_card_hash` 有
    UNIQUE 约束（models.py `uk_salary_profile_id_card`），数据库层已经拦死了，
    再查一遍是永远不会触发的死代码——而死代码配上测试会让人以为这条防线存在。
    档案层查银行卡（只有普通索引，可以撞），身份证重复的真实风险在**导入表**里，
    由 `_check_import` 的 duplicate 分支覆盖。

    重号查的是 hash 不是明文——明文只在加解密边界出现，比对用摘要就够了。
    """
    out: list[dict[str, Any]] = []

    groups: dict[str, list[SalaryEmployeeProfile]] = defaultdict(list)
    for p in profiles:
        val = (p.bank_card_hash or "").strip()
        if val:  # NULL 不算重复——空值互相「相等」会把所有没录的人凑成一组
            groups[val].append(p)
    for members in groups.values():
        if len(members) < 2:
            continue
        others = "、".join(f"{m.name}({m.emp_no})" for m in members)
        for p in members:
            out.append(_item(
                KIND_BANK_CARD_DUPLICATE, BLOCKING,
                f"银行卡与他人重复：{others}",
                "确认是否真的共用账户；不是的话必有一个录错，"
                "银行盘会把两个人的钱打进同一张卡",
                employee_id=p.id, emp_no=p.emp_no, name=p.name,
                ref={"peers": [m.id for m in members if m.id != p.id]},
            ))

    for p in profiles:
        # 底薪来源三选一：手动定薪 > 职级表 > 无。三个都没有的话 M3 会拿不到基数，
        # 与其到计算时抛异常，不如在这里点名。
        if p.base_salary_override is None and not (p.grade_code or "").strip():
            out.append(_item(
                KIND_BASE_SALARY_MISSING, BLOCKING,
                f"{p.name} 既没有职级也没有手动定薪，算不出底薪",
                "在档案里选职级，或直接填「手动定薪」（非职级岗位走这条）",
                employee_id=p.id, emp_no=p.emp_no, name=p.name,
            ))
    return out


# ---------------------------------------------------------------------------
# 记录级检查（M3：依赖 salary_record，计算后才有数据）
# ---------------------------------------------------------------------------

def check_records(db: Session, period: SalaryPeriod) -> list[dict[str, Any]]:
    """计算后才查得出的四类：负数实发 / 保底触发 / 月中加权 / 人工覆盖有偏差。

    负数实发是 blocking——但它拦的是 **confirm**，不是 calculate（不算出来
    根本不知道它是负的）。所以这里照常标 blocking 让面板置顶，`collect` 的
    `ready_to_calculate` 分母里把它排除（见 _PRE_CALC_KINDS）。
    """
    from app.salary.models import SalaryRecord

    rows = (
        db.query(SalaryRecord, SalaryEmployeeProfile)
        .outerjoin(SalaryEmployeeProfile,
                   SalaryEmployeeProfile.id == SalaryRecord.employee_id)
        .filter(SalaryRecord.period_id == period.id)
        .order_by(SalaryRecord.seq_no)
        .all()
    )
    out: list[dict[str, Any]] = []
    for row, profile in rows:
        emp = {"employee_id": row.employee_id,
               "emp_no": profile.emp_no if profile else None,
               "name": profile.name if profile else None}
        flags = set(row.calc_flags or [])

        if "negative_net" in flags:
            out.append(_item(
                KIND_NEGATIVE_NET, BLOCKING,
                f"{emp['name']} 实发为负（{row.net_salary}），不能锁定发放",
                "在明细表处理：清零挂账下月，或用其他款冲抵；处理后重新计算",
                **emp, ref={"record_id": row.id, "net_salary": str(row.net_salary)},
            ))
        if "guaranteed_topup" in flags:
            out.append(_item(
                KIND_GUARANTEED_TOPUP, INFO,
                f"{emp['name']} 触发保底补足，补贴 {row.subsidy_auto} 元",
                "核对保底金额与缺勤扣款无误即可忽略",
                **emp, ref={"record_id": row.id},
            ))
        if "mid_month_weighted" in flags:
            out.append(_item(
                KIND_MID_MONTH_WEIGHTED, INFO,
                f"{emp['name']} 月中调薪/转正，底薪按 30 天基数加权为 {row.base_salary}",
                "核对调薪/转正生效日；口径不对先到调薪记录修正再重算",
                **emp, ref={"record_id": row.id},
            ))
        # A2：manual 盖着且与 auto 不一致。重算后 auto 变了 manual 还在，差异
        # 就在这里——复核者决定是放弃覆盖还是确认 manual 才是对的。
        for col, label in (("bonus", "奖励"), ("performance", "绩效"),
                           ("other", "其他款"), ("subsidy", "补贴")):
            manual = getattr(row, f"{col}_manual")
            auto = getattr(row, f"{col}_auto")
            if manual is not None and auto is not None and manual != auto:
                out.append(_item(
                    KIND_MANUAL_OVERRIDE, INFO,
                    f"{emp['name']} 的{label}人工值 {manual} 与引擎值 {auto} 不一致",
                    "确认人工值正确可忽略；以引擎为准则在明细行清除该列的人工覆盖",
                    **emp, ref={"record_id": row.id, "field": col,
                                "manual": str(manual), "auto": str(auto)},
                ))
    return out


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def collect(db: Session, period: SalaryPeriod, *, include_records: bool = True) -> dict[str, Any]:
    """跑全部检查，聚合成一屏待办。

    返回结构里 `blocking_count` 是核心：它就是「能不能进计算」的答案。
    前端拿它决定「下一步」按钮的可用性——把判断留给前端自己数，
    迟早会数出跟后端不一样的结果。

    `include_records=False` 给计算门用：记录级异常（负数实发）是计算的**产物**，
    拿它当计算的前置条件就是死锁——不算出来永远不知道它是负的。
    """
    profiles = _payroll_profiles(db)
    items: list[dict[str, Any]] = []
    items += check_attendance(db, period, profiles)
    items += check_insurance(db, period, profiles)
    items += check_fund(db, period, profiles)
    items += check_profiles(db, profiles)
    if include_records:
        items += check_records(db, period)

    by_kind: dict[str, int] = defaultdict(int)
    kind_severity: dict[str, str] = {}
    for it in items:
        by_kind[it["kind"]] += 1
        # 同一 kind 的严重度是固定的（每处 _item 调用都写死了），这里取到即用。
        kind_severity.setdefault(it["kind"], it["severity"])
    blocking = [it for it in items if it["severity"] == BLOCKING]
    # 「可以进计算了吗」只看前置异常：记录级 blocking（负数实发）是计算的产物，
    # 拦的是 confirm。混进分母的话，算出一个负数就永远不能再重算——死锁。
    pre_blocking = [it for it in blocking if it["kind"] in _PRE_CALC_KINDS]

    # blocking 排在前面：HR 从上往下处理，致命的必须先出现。
    # 同严重度内按 kind 聚在一起，一类一类处理比在人名之间跳来跳去快。
    items.sort(key=lambda it: (it["severity"] != BLOCKING, it["kind"],
                               it["emp_no"] or "", it["name"] or ""))
    return {
        "period_id": period.id,
        "status": period.status,
        "items": items,
        "total": len(items),
        "blocking_count": len(blocking),
        "info_count": len(items) - len(blocking),
        "by_kind": [
            # severity 一并给出：前端的分类筛选角标要按它上色，
            # 让前端照着 kind 名再猜一次「这类算不算致命」必然会猜错。
            {"kind": k, "kind_label": KIND_LABELS.get(k, k), "count": v,
             "severity": kind_severity.get(k, INFO)}
            for k, v in sorted(by_kind.items())
        ],
        "payroll_headcount": len(profiles),
        # 「可以进计算了吗」由后端回答，不让前端自己数
        "ready_to_calculate": len(pre_blocking) == 0,
    }
