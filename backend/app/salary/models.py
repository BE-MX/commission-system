"""SQLAlchemy models for the salary module (092 migration).

10 张表，按角色分三组：
- 主数据：employee_profile / grade_table / rule_param / dept_mapping / change_log
- 批次输入：period / attendance / insurance_import / fund_import
- 批次输出：record（工资表 23 列落库 + confirmed 时的档案快照）

设计文档 docs/requirements/2026-07-21-salary-module.md §4。金额列统一
Numeric(12, 2)——工资域不允许 float，分位一致是 3 月复算的验收标准。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.dialects import mysql

from app.auth import models as _auth_models  # noqa: F401 - 注册 ark_users 供 FK 解析
from app.core.database import Base

# 金额与工时的统一精度。MONEY 到分，HOURS 到 0.01 小时（day_hours=7.83 需要两位）
MONEY = Numeric(12, 2)
HOURS = Numeric(8, 2)
# ark_users.id 是 INT UNSIGNED，FK 与操作人列都必须同型（红线：FK 类型完全一致）。
# with_variant 让 SQLite 测试库回落普通 Integer。
USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class SalaryEmployeeProfile(Base):
    """员工薪资档案：1 人 1 行，工资口径的主数据。

    与 ark_users 是弱关联（user_id 可空）——质检等岗位没有平台账号，
    档案不能因此缺人，否则这些人永远进不了工资表。
    """

    __tablename__ = "ark_salary_employee_profile"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"),
        nullable=True, comment="平台账号 ark_users.id（可空：无账号员工）",
    )
    emp_no = Column(String(32), nullable=False, comment="工号（唯一，消灭 3/003 混写）")
    name = Column(String(64), nullable=False, comment="姓名")

    # PII：密文列存储、哈希列做唯一与匹配（见 pii.py 注释）
    id_card_cipher = Column(String(255), nullable=True, comment="身份证密文 AES-GCM")
    id_card_hash = Column(String(64), nullable=True, comment="身份证 HMAC 摘要（唯一/匹配用）")
    bank_card_cipher = Column(String(255), nullable=True, comment="银行卡密文 AES-GCM")
    bank_card_hash = Column(String(64), nullable=True, comment="银行卡 HMAC 摘要（唯一/查重用）")
    bank_name = Column(String(64), nullable=True, comment="开户行")

    hire_date = Column(Date, nullable=True, comment="入职日期（工龄与月中入职计薪依据）")
    regular_date = Column(Date, nullable=True, comment="转正日期")
    leave_date = Column(Date, nullable=True, comment="离职日期")
    status = Column(String(16), nullable=False, default="active", comment="active=在职,left=离职")

    dept_detail = Column(String(64), nullable=True, comment="明细部门（→ dept_mapping 查大部门）")
    # 大部门原则上由 dept_mapping 推导，但 3 月表实证：跟单1部 7 人里 6 人归后综部、
    # 吕德洋（业务总监）归业务部——大部门不是纯粹的部门属性，管理岗按人挂靠。
    # 该列非空时优先于映射表，让 HR 不必为一个人再拆一个明细部门。
    dept_group_override = Column(String(64), nullable=True, comment="汇总大部门-按人覆盖（优先于 dept_mapping）")
    position = Column(String(64), nullable=True, comment="职务（单一真相源，两 sheet 同源导出）")
    grade_scheme = Column(
        String(32), nullable=True,
        comment="职级赛道：resource/develop/merch/manage/none",
    )
    grade_code = Column(String(16), nullable=True, comment="职级码 P1..P10 / M1..M6 / F1..F6")

    base_salary_override = Column(MONEY, nullable=True, comment="手动定薪（非职级岗位，优先于职级表）")
    probation_salary = Column(MONEY, nullable=True, comment="试用期底薪")
    probation_note = Column(String(255), nullable=True, comment="试用期备注文案（进汇总表备注列）")
    guaranteed_salary = Column(MONEY, nullable=True, comment="保底工资")
    guaranteed_from = Column(Date, nullable=True, comment="保底生效起")
    guaranteed_to = Column(Date, nullable=True, comment="保底生效止")

    insurance_entity = Column(String(64), nullable=True, comment="参保主体（丽丝发/鄄城分公司）")
    payroll_included = Column(SmallInteger, nullable=False, default=1, comment="1=发薪,0=仅参保（白名单）")
    fund_included = Column(SmallInteger, nullable=False, default=1, comment="1=缴公积金")

    dingtalk_userid = Column(String(64), nullable=True, comment="钉钉 userid（考勤取数键）")
    mobile = Column(String(32), nullable=True, comment="手机号")
    remark = Column(Text, nullable=True, comment="备注")

    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("emp_no", name="uk_salary_profile_emp_no"),
        UniqueConstraint("id_card_hash", name="uk_salary_profile_id_card"),
        # 银行卡只建普通索引（093 从 UNIQUE 降级）：共卡代发是真实存在的，
        # UNIQUE 会让第二个人永远建不了档案。查重靠这个索引，判断交给人。
        Index("idx_salary_profile_bank_card", "bank_card_hash"),
        Index("idx_salary_profile_status", "status"),
        Index("idx_salary_profile_user", "user_id"),
        # UNIQUE（096）：一个钉钉 userid 只能绑一个人。撞号会让考勤同步静默丢掉
        # 其中一个人，而所有告警指标都显示正常（详见 096 迁移的说明）。
        # UNIQUE 放过多个 NULL，所以没绑钉钉的人不受影响。
        Index("uk_salary_profile_dingtalk", "dingtalk_userid", unique=True),
        Index("idx_salary_profile_name", "name"),
        {"comment": "薪资档案-员工主数据（PII 密文+哈希双列）"},
    )


class SalaryDeptMapping(Base):
    """明细部门 → 汇总大部门映射。配置关系，不冗余进 66 行档案。"""

    __tablename__ = "ark_salary_dept_mapping"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    dept_detail = Column(String(64), nullable=False, comment="明细部门名（工资表明细 sheet 口径）")
    dept_group = Column(String(64), nullable=False, comment="汇总大部门（后综部/业务部…）")
    sort_order = Column(Integer, nullable=False, default=0, comment="汇总表分组排序")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("dept_detail", name="uk_salary_dept_mapping_detail"),
        {"comment": "薪资-部门分组映射"},
    )


class SalaryGradeTable(Base):
    """职级薪级表（版本化）。effective_from/to 落地「2026/04/01-更新新版本为止」。"""

    __tablename__ = "ark_salary_grade_table"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    scheme = Column(String(32), nullable=False, comment="赛道：resource/develop/merch/manage")
    grade_code = Column(String(16), nullable=False, comment="职级码")
    base_salary = Column(MONEY, nullable=True, comment="底薪")
    perf_full = Column(MONEY, nullable=True, comment="满绩效金额")
    std_salary = Column(MONEY, nullable=True, comment="标准工资（管理岗）")
    perf_target_monthly = Column(MONEY, nullable=True, comment="月均业绩标准")
    new_sign_min = Column(Integer, nullable=True, comment="月均新签下限（个）")
    team_rate = Column(Numeric(8, 4), nullable=True, comment="团队提成参考费率")
    effective_from = Column(Date, nullable=False, comment="生效起日")
    effective_to = Column(Date, nullable=True, comment="生效止日（NULL=当前版本）")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("scheme", "grade_code", "effective_from", name="uk_salary_grade_ver"),
        Index("idx_salary_grade_lookup", "scheme", "grade_code", "effective_from"),
        {"comment": "薪资-职级薪级表（版本化）"},
    )


class SalaryRuleParam(Base):
    """规则参数版本化 KV。计算时整批快照进 period.param_snapshot。

    value 走 String 而非 Numeric：参数里既有 7.83 也有 0.7 也有将来可能的枚举/JSON，
    统一字符串 + 读取侧显式转型，比给每种类型开一列干净。
    """

    __tablename__ = "ark_salary_rule_param"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    param_key = Column(String(64), nullable=False, comment="参数键，如 day_hours")
    param_value = Column(String(255), nullable=False, comment="参数值（字符串存，读取侧转型）")
    value_type = Column(String(16), nullable=False, default="decimal", comment="decimal/int/bool/str")
    category = Column(String(32), nullable=True, comment="分组：attendance/insurance/seniority…")
    description = Column(String(255), nullable=True, comment="含义说明（配置页展示）")
    effective_from = Column(Date, nullable=False, comment="生效起日")
    effective_to = Column(Date, nullable=True, comment="生效止日（NULL=当前版本）")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("param_key", "effective_from", name="uk_salary_param_ver"),
        Index("idx_salary_param_lookup", "param_key", "effective_from"),
        {"comment": "薪资-规则参数（版本化 KV）"},
    )


class SalaryChangeLog(Base):
    """调薪/调级/转正记录。月中生效的加权计薪依据（陈佳乐 3775 案例）。"""

    __tablename__ = "ark_salary_change_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    employee_id = Column(
        BigInteger, ForeignKey("ark_salary_employee_profile.id", ondelete="CASCADE"),
        nullable=False, comment="员工档案 id",
    )
    change_type = Column(String(32), nullable=False, comment="raise=调薪,grade=调级,regular=转正")
    effective_date = Column(Date, nullable=False, comment="生效日（月中则触发加权）")
    old_value = Column(JSON, nullable=True, comment="变更前快照")
    new_value = Column(JSON, nullable=True, comment="变更后快照")
    reason = Column(String(255), nullable=True, comment="变更原因")
    created_by = Column(USER_ID, nullable=True, comment="操作人 ark_users.id")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_salary_change_emp_date", "employee_id", "effective_date"),
        {"comment": "薪资-调薪调级转正台账"},
    )


class SalaryPeriod(Base):
    """月度批次。状态机与乐观锁在此，计算参数在此冻结。"""

    __tablename__ = "ark_salary_period"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    year_month = Column(String(7), nullable=False, comment="批次月份 YYYY-MM")
    status = Column(
        String(24), nullable=False, default="draft",
        comment="draft/attendance_synced/imported/calculated/reviewing/confirmed",
    )
    status_version = Column(
        Integer, nullable=False, default=0,
        comment="批次级乐观锁：状态跃迁前校验，防重算与锁定并发碰撞",
    )
    workday_count = Column(Integer, nullable=True, comment="当月应出勤工作日数")
    # 自动推算只按周一~周五数，含法定节假日的月份必然偏大，标 needs_review 让批次页
    # 提示 HR 覆盖。持久化而非只落事件 payload：前端拿不到的标记等于没有这套机制。
    workday_source = Column(
        String(16), nullable=True,
        comment="工作日数来源 weekday_auto/needs_review/manual",
    )
    natural_days = Column(Integer, nullable=True, comment="当月自然日数")
    param_snapshot = Column(JSON, nullable=True, comment="计算时冻结的 rule_param 全量快照")
    calculated_at = Column(DateTime, nullable=True, comment="最近一次重算时间")
    confirmed_at = Column(DateTime, nullable=True, comment="锁定时间")
    confirmed_by = Column(USER_ID, nullable=True, comment="锁定人 ark_users.id")
    unlocked_at = Column(DateTime, nullable=True, comment="最近一次 admin 解锁时间（A4 留痕）")
    unlock_reason = Column(String(255), nullable=True, comment="解锁原因")
    remark = Column(Text, nullable=True, comment="批次备注")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("year_month", name="uk_salary_period_ym"),
        Index("idx_salary_period_status", "status"),
        {"comment": "薪资-月度批次"},
    )


class SalaryAttendance(Base):
    """考勤汇总（批次×员工）。钉钉拉取或人工录入，先落库供核对再进计算。"""

    __tablename__ = "ark_salary_attendance"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    period_id = Column(
        BigInteger, ForeignKey("ark_salary_period.id", ondelete="CASCADE"),
        nullable=False, comment="批次 id",
    )
    employee_id = Column(
        BigInteger, ForeignKey("ark_salary_employee_profile.id", ondelete="CASCADE"),
        nullable=False, comment="员工档案 id",
    )
    due_days = Column(Numeric(6, 2), nullable=True, comment="应出勤天数")
    actual_days = Column(Numeric(6, 2), nullable=True, comment="实出勤天数（<15 触发基准切换）")
    personal_leave_hours = Column(HOURS, nullable=True, comment="事假小时")
    sick_leave_hours = Column(HOURS, nullable=True, comment="病假小时")
    annual_leave_days = Column(Numeric(6, 2), nullable=True, comment="年假天数（不破全勤）")
    annual_leave_remain = Column(Numeric(6, 2), nullable=True, comment="年假剩余额度")
    late_count = Column(Integer, nullable=False, default=0, comment="迟到次数")
    early_leave_count = Column(Integer, nullable=False, default=0, comment="早退次数")
    miss_punch_count = Column(Integer, nullable=False, default=0, comment="漏打卡次数")
    absent_count = Column(Numeric(6, 2), nullable=False, default=0, comment="旷工天数")
    full_attendance = Column(SmallInteger, nullable=False, default=0, comment="1=全勤")
    sync_source = Column(String(16), nullable=False, default="manual", comment="dingtalk/manual")
    raw_payload = Column(JSON, nullable=True, comment="钉钉原始返回（排障用）")
    synced_at = Column(DateTime, nullable=True, comment="同步时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", name="uk_salary_attendance_pe"),
        Index("idx_salary_attendance_period", "period_id"),
        {"comment": "薪资-考勤汇总"},
    )


class SalaryInsuranceImport(Base):
    """社保导入行。id_card_hash 是与档案匹配的唯一途径（源表是明文身份证）。"""

    __tablename__ = "ark_salary_insurance_import"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    period_id = Column(
        BigInteger, ForeignKey("ark_salary_period.id", ondelete="CASCADE"),
        nullable=False, comment="批次 id",
    )
    employee_id = Column(
        BigInteger, ForeignKey("ark_salary_employee_profile.id", ondelete="SET NULL"),
        nullable=True, comment="匹配到的档案 id（未匹配为 NULL，进异常面板）",
    )
    entity = Column(String(64), nullable=True, comment="参保主体（对应源表 sheet）")
    name = Column(String(64), nullable=True, comment="源表姓名")
    id_card_hash = Column(String(64), nullable=True, comment="身份证 HMAC 摘要（匹配键）")
    id_card_cipher = Column(String(255), nullable=True, comment="身份证密文（留档，不用于匹配）")
    base_amount = Column(MONEY, nullable=True, comment="缴费基数")
    personal_total = Column(MONEY, nullable=True, comment="个人合计（进减项）")
    company_total = Column(MONEY, nullable=True, comment="单位合计（不进工资表，仅对账）")
    detail_json = Column(JSON, nullable=True, comment="各险种明细（养老/医疗/失业/工伤/生育）")
    match_status = Column(
        String(16), nullable=False, default="matched",
        comment="matched/not_payroll(参保未发薪)/unmatched(未识别)",
    )
    dept_text = Column(String(64), nullable=True, comment="源表部门文本")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_salary_ins_period", "period_id"),
        Index("idx_salary_ins_hash", "period_id", "id_card_hash"),
        Index("idx_salary_ins_match", "period_id", "match_status"),
        {"comment": "薪资-社保导入行"},
    )


class SalaryFundImport(Base):
    """公积金导入行。结构同社保但字段更少，单独建表避免 match_status 语义混淆。"""

    __tablename__ = "ark_salary_fund_import"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    period_id = Column(
        BigInteger, ForeignKey("ark_salary_period.id", ondelete="CASCADE"),
        nullable=False, comment="批次 id",
    )
    employee_id = Column(
        BigInteger, ForeignKey("ark_salary_employee_profile.id", ondelete="SET NULL"),
        nullable=True, comment="匹配到的档案 id（未匹配为 NULL）",
    )
    name = Column(String(64), nullable=True, comment="源表姓名")
    id_card_hash = Column(String(64), nullable=True, comment="身份证 HMAC 摘要（匹配键）")
    id_card_cipher = Column(String(255), nullable=True, comment="身份证密文（留档）")
    base_amount = Column(MONEY, nullable=True, comment="缴存基数")
    personal_amount = Column(MONEY, nullable=True, comment="个人缴存额（进减项）")
    company_amount = Column(MONEY, nullable=True, comment="单位缴存额（仅对账）")
    match_status = Column(String(16), nullable=False, default="matched", comment="matched/not_payroll/unmatched")
    dept_text = Column(String(64), nullable=True, comment="源表部门文本")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_salary_fund_period", "period_id"),
        Index("idx_salary_fund_hash", "period_id", "id_card_hash"),
        Index("idx_salary_fund_match", "period_id", "match_status"),
        {"comment": "薪资-公积金导入行"},
    )


class SalaryRecord(Base):
    """工资明细行（批次×员工），工资表 23 列落库。

    列的三种形态（设计文档 §4.1 决策 A2）：
    - 引擎列：只有 final，引擎每次重算直接覆盖
    - 三元组列：auto/manual/final，`final = coalesce(manual, auto)`；
      `manual IS NOT NULL AND manual != auto` 即「引擎值已变但被人工覆盖」，进异常面板
    - 纯手动列：个税，引擎不产出

    注意源表口径：减项列（social/fund/absence/deduct_subtotal）在 HR 原表里
    **本身就是负数**，引擎必须照此产出，不要写成正数再相减，否则实发校验正负翻车。

    档案快照列在 confirmed 时冻结。之后银行盘/汇总表/重导出一律读快照，
    不回查活档案——否则锁定后员工换卡会污染历史批次（§2.5 错误 2 的系统版）。
    """

    __tablename__ = "ark_salary_record"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    period_id = Column(
        BigInteger, ForeignKey("ark_salary_period.id", ondelete="CASCADE"),
        nullable=False, comment="批次 id",
    )
    employee_id = Column(
        BigInteger, ForeignKey("ark_salary_employee_profile.id", ondelete="CASCADE"),
        nullable=False, comment="员工档案 id",
    )
    seq_no = Column(Integer, nullable=True, comment="明细表序号")

    # ── 出勤（引擎输入回写，便于导出与核对）────────────────
    due_days = Column(Numeric(6, 2), nullable=True, comment="应出勤")
    actual_days = Column(Numeric(6, 2), nullable=True, comment="实出勤")

    # ── 引擎列（单字段 final）──────────────────────────────
    base_salary = Column(MONEY, nullable=True, comment="底薪（月中调薪按 B2 加权）")
    seniority_pay = Column(MONEY, nullable=True, comment="工龄工资")
    attendance_bonus = Column(MONEY, nullable=True, comment="全勤奖")
    social_insurance = Column(MONEY, nullable=True, comment="社保个人（负数，同源表口径）")
    housing_fund = Column(MONEY, nullable=True, comment="公积金个人（负数）")
    absence_deduction = Column(MONEY, nullable=True, comment="缺勤扣款（负数）")
    add_subtotal = Column(MONEY, nullable=True, comment="增项小计")
    deduct_subtotal = Column(MONEY, nullable=True, comment="减项小计（负数）")
    net_salary = Column(MONEY, nullable=True, comment="应发/实发（<0 强制进异常清单）")

    # ── 三元组列（auto / manual / final）──────────────────
    bonus_auto = Column(MONEY, nullable=True, comment="奖励-引擎值")
    bonus_manual = Column(MONEY, nullable=True, comment="奖励-人工覆盖（NULL=未覆盖）")
    bonus_final = Column(MONEY, nullable=True, comment="奖励-生效值 coalesce(manual,auto)")
    performance_auto = Column(MONEY, nullable=True, comment="绩效-引擎值（P1 为空，P2 自动化）")
    performance_manual = Column(MONEY, nullable=True, comment="绩效-人工覆盖")
    performance_final = Column(MONEY, nullable=True, comment="绩效-生效值")
    other_auto = Column(MONEY, nullable=True, comment="其他款-引擎值（可正可负）")
    other_manual = Column(MONEY, nullable=True, comment="其他款-人工覆盖")
    other_final = Column(MONEY, nullable=True, comment="其他款-生效值")
    subsidy_auto = Column(MONEY, nullable=True, comment="补贴-引擎值")
    subsidy_manual = Column(MONEY, nullable=True, comment="补贴-人工覆盖")
    subsidy_final = Column(MONEY, nullable=True, comment="补贴-生效值")

    # ── 纯手动列 ─────────────────────────────────────────
    income_tax_amount = Column(MONEY, nullable=True, comment="个税（P1 纯手动，P3 评估累计预扣）")
    net_after_tax = Column(MONEY, nullable=True, comment="税后实发")

    # ── 档案快照（confirmed 时冻结）───────────────────────
    snap_emp_no = Column(String(32), nullable=True, comment="快照-工号")
    snap_name = Column(String(64), nullable=True, comment="快照-姓名")
    snap_dept_detail = Column(String(64), nullable=True, comment="快照-明细部门")
    snap_dept_group = Column(String(64), nullable=True, comment="快照-汇总大部门")
    snap_position = Column(String(64), nullable=True, comment="快照-职务")
    snap_bank_card_cipher = Column(String(255), nullable=True, comment="快照-银行卡密文")
    snap_bank_name = Column(String(64), nullable=True, comment="快照-开户行")
    snapshot_at = Column(DateTime, nullable=True, comment="快照冻结时间")

    # ── 自动文案与审计 ───────────────────────────────────
    remark_summary = Column(String(255), nullable=True, comment="汇总表备注（自动生成）")
    leave_remark = Column(String(255), nullable=True, comment="请假时间文案（自动生成）")
    row_version = Column(Integer, nullable=False, default=0, comment="行级乐观锁（复核期并发编辑）")
    calculated_at = Column(DateTime, nullable=True, comment="最近计算时间")
    modified_by = Column(USER_ID, nullable=True, comment="最近人工修改人 ark_users.id")
    modify_reason = Column(String(255), nullable=True, comment="修改原因")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", name="uk_salary_record_pe"),
        Index("idx_salary_record_period", "period_id"),
        Index("idx_salary_record_emp", "employee_id"),
        {"comment": "薪资-工资明细行（含档案快照）"},
    )





class SalaryPeriodEvent(Base):
    """批次事件留痕（094 迁移）。谁在什么时候把哪个批次从什么状态改成了什么状态。

    **不复用 SalaryChangeLog**：那张是调薪/调级/转正台账，M3 引擎按
    employee_id + effective_date 读它做月中加权，混入批次级事件会污染那条查询，
    且它的 employee_id 是 NOT NULL——批次事件没有员工可填。

    解锁原因落在这里，是决策 A4「前次导出打作废水印」的判定依据。
    """

    __tablename__ = "ark_salary_period_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    period_id = Column(
        BigInteger, ForeignKey("ark_salary_period.id", ondelete="CASCADE"),
        nullable=False, comment="批次 id",
    )
    event_type = Column(
        String(32), nullable=False,
        comment="create/transition/unlock/workday_update/import/attendance_sync",
    )
    from_status = Column(String(24), nullable=True, comment="跃迁前状态")
    to_status = Column(String(24), nullable=True, comment="跃迁后状态")
    status_version = Column(Integer, nullable=True, comment="跃迁后的乐观锁版本")
    reason = Column(String(255), nullable=True, comment="原因（解锁必填）")
    payload = Column(JSON, nullable=True, comment="事件附加数据")
    created_by = Column(USER_ID, nullable=True, comment="操作人 ark_users.id")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="发生时间")

    __table_args__ = (
        Index("idx_salary_period_event_pid", "period_id", "id"),
        {"comment": "薪资-批次事件留痕"},
    )
