"""薪资模块 — 钉钉考勤取数（M2-d）。

**纯取数层：不碰 session、不写库。** 与 `import_service` 同样的分工——落库、匹配、
事务在 `attendance_service`。这样这一层能在没有数据库的环境下测，也能单独拿去排障。

## 2026-08-07 实测的四个硬约束（探测脚本跑在真实企业上，不是看文档猜的）

1. **`getcolumnval` 每次最多 20 个列 id。** 21 个就返回 `errcode=41
   Invalid arguments:column_id_list`。企业当前有 38 个带 id 的列，所以必须分片调用。
   这个上限官方文档没写。

2. **请假五列（年假/事假/病假/产假/产检）的 `id` 是 `None`。** 它们在报表里看得见，
   但没有列 id，`getcolumnval` 拿不到。→ 报表这条路取不到；**请假改走
   `getleavestatus` 明细路**（2026-08-07 权限开通后接入，见文件下方「请假自动拉取」）。

3. **`attendance/list`（打卡明细）与 `getleavestatus`（请假明细）2026-08-07 已开通**
   （`qyapi_get_attendance_data` 等）。假期类型/年假额度（`vacation/type/list`、
   `vacation/quota/list`）还需 `qyapi_holiday_readonly`——类型映射拿不到时整个
   请假管线降级为人工录入，主同步不受影响（降级原因进同步摘要的 `leave_degraded`）。

4. **钉钉的「应出勤天数」3 月合计 = 22（工作日口径），不是自然日 31。**
   所以它**不能直接当 `due_days`**——满月员工的应出天数由规则参数 `full_month_days=31`
   决定（决策 B1）。这里只把它当 `dingtalk_should_days` 原样带出去供人核对，
   谁把它接进缺勤扣款的分母，66 个人的扣款就全错。

## 列值的形态

`getcolumnval` 返回的是**逐日值**，不是月度汇总：一个列一个月 31 条 `{date, value}`。
所以月度值要自己按列语义聚合——天数/次数类求和，「工作时长」这种也是求和。
`value` 是字符串（`"1.0"` / `"0"`），空值可能是 `""`。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.dingtalk.client import DingTalkError, get_dingtalk_client

logger = logging.getLogger("commission")

# 实测上限 20（见模块 docstring 约束 1）。留一格余量不是迷信——
# 钉钉侧改上限的可能性远小于我们这边多传一列的可能性。
MAX_COLUMNS_PER_CALL = 20

# 权限未开通的错误码。钉钉在 topapi 与新版接口上包法不同：
# attendance/list 直接给 60011，getleavestatus 给 88 外层套 60011 子码。
_SCOPE_ERROR_CODES = (60011, 88)


class AttendanceSourceError(Exception):
    """取数失败。带上人话——这个异常会一路冒到 HR 的屏幕上。"""


# ---------------------------------------------------------------------------
# 列语义映射
# ---------------------------------------------------------------------------

# alias → 我们的字段名。**按 alias 映射，绝不写死列 id**：
# id 是租户级的（本企业 340771676 起），换个企业或钉钉重建报表就全变。
# alias 是钉钉的稳定标识符，实测同一套 alias 跨企业一致。
COLUMN_ALIASES: dict[str, str] = {
    "should_attendance_days": "dingtalk_should_days",
    "attendance_days": "actual_days_raw",
    "late_times": "late_count",
    "serious_late_times": "serious_late_count",
    "leave_early_times": "early_leave_count",
    "on_work_lack_card_times": "miss_punch_on",
    "off_work_lack_card_times": "miss_punch_off",
    "absenteeism_days": "absent_days",
    "making_up_lack_times": "makeup_count",
    "attendance_work_time": "work_hours",
}

# 请假五列取不到（约束 2），但要让上层知道「不是忘了取，是取不到」。
UNAVAILABLE_LEAVE_COLUMNS = ("年假", "事假", "病假", "产假", "产检")


@dataclass
class DayValue:
    date: str
    value: str


@dataclass
class PersonAttendance:
    """一个人一个月的考勤聚合值。全部是**钉钉原样口径**，没做任何薪资规则折算。

    折算（7.83 折天、满月 31 天基准、全勤判定）属于计算口径，放 attendance_service
    和 M3；混进取数层会让「钉钉给的」和「我们算的」在排障时分不开。
    """
    userid: str
    values: dict[str, Decimal] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # {字段名: 无法解析的天数}。非空 = 这个人的该列聚合值偏小，见 `_to_decimal`。
    dirty: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


def _to_decimal(raw: Any) -> tuple[Decimal, bool]:
    """钉钉的 value 是字符串，空值给 ""。返回 (值, 是否脏值)。

    **脏值必须回报，不能只是静默算 0**（红线 6）。危险的不是全列坏掉——那种情况
    聚合出 0，一眼能看出不对；危险的是 31 天里坏了 11 天，聚合出 20.0 而真值是 31，
    结果完全像个正常数字，只是少了 11 天。所以 `aggregate_column` 会把脏值条数
    一路带到同步摘要里，让 HR 知道这一列信不信得过。

    空串不算脏：钉钉对「那天没有该项记录」就是给 ""，这是正常语义。
    """
    if raw is None or raw == "":
        return Decimal("0"), False
    try:
        return Decimal(str(raw).strip()), False
    except (InvalidOperation, ValueError):
        return Decimal("0"), True


def aggregate_column(day_values: list[dict[str, Any]]) -> Decimal:
    """把一列 31 天的逐日值聚合成月度值。脏值条数见 `aggregate_column_detail`。

    天数类（出勤天数 1.0/0.0）、次数类（迟到 0/1）、时长类都是求和语义。
    钉钉没有给月度汇总接口，这个加法就是月度值本身。
    """
    return aggregate_column_detail(day_values)[0]


def aggregate_column_detail(day_values: list[dict[str, Any]]) -> tuple[Decimal, int]:
    """聚合并回报脏值条数，供 `fetch_person` 汇总成告警。"""
    total = Decimal("0")
    dirty = 0
    for item in day_values or []:
        value, bad = _to_decimal(item.get("value"))
        total += value
        dirty += 1 if bad else 0
    return total, dirty


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------

async def fetch_columns(client=None) -> tuple[dict[str, dict], list[str]]:
    """拉列定义，返回 (alias → 列对象, 取不到的请假列名)。

    每次同步都重新拉而不是缓存到配置里：HR 在钉钉后台调整报表列是常事，
    缓存住只会让某个月的数据静默变成 0——比报错难查一百倍。
    """
    client = client or get_dingtalk_client()
    try:
        data = await client.post("topapi/attendance/getattcolumns", json_data={})
    except DingTalkError as exc:
        raise AttendanceSourceError(f"读取钉钉考勤报表列定义失败：{exc}") from exc

    columns = (data.get("result") or {}).get("columns") or []
    by_alias: dict[str, dict] = {}
    missing_leave: list[str] = []
    for col in columns:
        alias = col.get("alias")
        if not col.get("id"):
            # 请假五列的 alias 都是 "leave_"（互相覆盖），只能按 name 记录
            if col.get("name") in UNAVAILABLE_LEAVE_COLUMNS:
                missing_leave.append(col["name"])
            continue
        if alias in COLUMN_ALIASES and alias not in by_alias:
            by_alias[alias] = col
    return by_alias, missing_leave


async def fetch_person(
    userid: str,
    columns: dict[str, dict],
    from_date: str,
    to_date: str,
    *,
    client=None,
) -> PersonAttendance:
    """拉一个人一个月的列值。分片调用（约束 1），任一片失败即整人标失败。

    单人失败不抛：调用方要按人隔离（红线 6），一个人的钉钉账号没绑对
    不该让另外 65 人同步不了。
    """
    client = client or get_dingtalk_client()
    ids = [str(col["id"]) for col in columns.values()]
    id_to_field = {str(col["id"]): COLUMN_ALIASES[alias] for alias, col in columns.items()}

    values: dict[str, Decimal] = {}
    raw: dict[str, Any] = {}
    dirty: dict[str, int] = {}

    for chunk in _chunk(ids, MAX_COLUMNS_PER_CALL):
        try:
            data = await client.post(
                "topapi/attendance/getcolumnval",
                json_data={
                    "userid": userid,
                    "column_id_list": ",".join(chunk),
                    "from_date": from_date,
                    "to_date": to_date,
                },
            )
        except DingTalkError as exc:
            return PersonAttendance(userid=userid, error=f"钉钉取数失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            return PersonAttendance(userid=userid, error=f"钉钉取数异常：{exc}")

        for group in (data.get("result") or {}).get("column_vals") or []:
            vo = group.get("column_vo") or {}
            col_id = str(vo.get("id") or "")
            field_name = id_to_field.get(col_id)
            if not field_name:
                continue
            day_values = group.get("column_vals") or []
            total, bad = aggregate_column_detail(day_values)
            values[field_name] = total
            raw[field_name] = day_values
            if bad:
                dirty[field_name] = bad
                logger.warning("钉钉考勤列有脏值 userid=%s 列=%s 坏 %s 天，聚合值 %s 偏小",
                               userid, field_name, bad, total)
                print(f"[salary.attendance_source] dirty userid={userid} "
                      f"col={field_name} bad_days={bad}", flush=True)

    if not values:
        return PersonAttendance(userid=userid, error="钉钉返回空数据（该员工当月无考勤记录或 userid 无效）")
    return PersonAttendance(userid=userid, values=values, raw=raw, dirty=dirty)


async def probe_scopes(client=None) -> dict[str, bool]:
    """探测打卡明细/请假明细两路权限是否已开通。

    这不是可有可无的诊断：这两路决定「迟到漏打卡次数」能不能自动拿到，
    而全勤奖 100 元直接挂在它上面。开通与否要明确写进同步结果给 HR 看，
    否则他会以为系统判的全勤是全自动的，实际上是半瞎的。
    """
    client = client or get_dingtalk_client()
    out = {"punch_detail": False, "leave_detail": False}
    try:
        await client.post("attendance/list", json_data={
            "workDateFrom": "2026-03-01 00:00:00",
            "workDateTo": "2026-03-02 00:00:00",
            "userIdList": [], "offset": 0, "limit": 1,
        })
        out["punch_detail"] = True
    except DingTalkError as exc:
        if exc.code not in _SCOPE_ERROR_CODES:
            out["punch_detail"] = True  # 别的错（比如参数）说明权限是通的
    except Exception:  # noqa: BLE001
        pass
    return out


def month_range(year: int, month: int, natural_days: int) -> tuple[str, str]:
    """钉钉要 'YYYY-MM-DD HH:MM:SS' 格式的闭区间。"""
    return (f"{year:04d}-{month:02d}-01 00:00:00",
            f"{year:04d}-{month:02d}-{natural_days:02d} 23:59:59")


async def fetch_many(
    userids: list[str],
    from_date: str,
    to_date: str,
    *,
    client=None,
    concurrency: int = 4,
) -> tuple[list[PersonAttendance], list[str]]:
    """批量取数，返回 (每人结果, 取不到的请假列名)。

    并发压到 4：实测连续快速调用会撞 850015「系统异常，请稍后重试」，
    那是钉钉的限流。66 个人 × 2 片 = 132 次调用，4 并发跑完约一分钟，
    对一个月跑一次的操作完全够用——为了快而被限流反而要整批重来。
    """
    client = client or get_dingtalk_client()
    columns, missing_leave = await fetch_columns(client=client)
    if not columns:
        raise AttendanceSourceError(
            "钉钉考勤报表里没有找到任何可识别的列。请确认企业考勤报表未被改名或停用。"
        )

    sem = asyncio.Semaphore(concurrency)

    async def one(uid: str) -> PersonAttendance:
        async with sem:
            return await fetch_person(uid, columns, from_date, to_date, client=client)

    results = await asyncio.gather(*(one(u) for u in userids))
    return list(results), missing_leave


# ---------------------------------------------------------------------------
# 请假自动拉取（2026-08-07 权限开通后接入：getleavestatus 已实测可用）
# ---------------------------------------------------------------------------
#
# 三个接口分工：
# - `vacation/type/list`：leave_code → 类型名/单位（事假/病假/年假的判定依据），
#   需要 `qyapi_holiday_readonly`；未开通时返回 {}，整个请假管线降级、主同步照常。
# - `getleavestatus`：每人每条的请假记录（start/end/duration_percent/unit/leave_code），
#   `qyapi_get_attendance_data` 已开（2026-08-07 实测牟亮亮 3/6 事假 2.5h 与工资表吻合）。
# - `vacation/quota/list`：年假余额（→ 汇总表「本年度剩余年假Y天」）。
#
# 两条口径钉死：
# 1. **跨月记录按时间重叠比例折算**。duration_percent 是整条请假的总量，
#    3/30–4/2 的 4 天假不做切割会把 4 月的 2 天也算进 3 月。
# 2. **类型名只认精确匹配**（事假/病假/年假）。HR 在钉钉侧自建的新类型
#   （调休、无薪事假……）一律进 unknown 清单报出来，绝不静默归入某个扣款项——
#    归错了就是算错钱。

LEAVE_STATUS_BATCH = 20   # getleavestatus 的 userid_list 上限
LEAVE_STATUS_PAGE = 50    # size 上限未见诸文档，50 是实测安全值

# 类型名 → 我们的字段语义。精确匹配，别加模糊包含——名字像不等于规则同。
LEAVE_TYPE_PERSONAL = "事假"
LEAVE_TYPE_SICK = "病假"
LEAVE_TYPE_ANNUAL = "年假"


async def fetch_leave_types(client=None) -> dict[str, dict[str, str]]:
    """leave_code → {'name', 'unit'}。权限未开通返回 {}（降级信号，不抛）。"""
    client = client or get_dingtalk_client()
    try:
        data = await client.post("topapi/attendance/vacation/type/list", json_data={})
    except DingTalkError as exc:
        if exc.code in _SCOPE_ERROR_CODES or "60011" in str(exc):
            logger.warning("假期类型接口权限未开通（qyapi_holiday_readonly），请假自动拉取降级")
            return {}
        raise AttendanceSourceError(f"读取钉钉假期类型失败：{exc}") from exc
    out: dict[str, dict[str, str]] = {}
    for t in data.get("result") or []:
        code = t.get("leave_code")
        if code:
            out[str(code)] = {"name": str(t.get("leave_name") or ""),
                              "unit": str(t.get("unit") or "")}
    return out


async def fetch_leave_records(
    userids: list[str],
    from_ms: int,
    to_ms: int,
    *,
    client=None,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """拉整批人的请假记录。返回 ({userid: [记录]}, 失败 userid 清单)。

    批量接口的隔离单位是「批」不是「人」：一批 20 人，某批失败只丢那 20 人，
    其余批照常（红线 6 在批量接口下的等价形态）。没记录的人给空 list——
    「钉钉确认本月无请假」是有效答案，上层据此把请假小时填 0。
    """
    client = client or get_dingtalk_client()
    out: dict[str, list[dict[str, Any]]] = {}
    failed: list[str] = []
    for batch in _chunk(userids, LEAVE_STATUS_BATCH):
        batch_records: dict[str, list[dict[str, Any]]] = {u: [] for u in batch}
        offset = 0
        try:
            while True:
                data = await client.post(
                    "topapi/attendance/getleavestatus",
                    json_data={
                        "userid_list": ",".join(batch),
                        "start_time": from_ms,
                        "end_time": to_ms,
                        "offset": offset,
                        "size": LEAVE_STATUS_PAGE,
                    },
                )
                result = data.get("result") or {}
                for rec in result.get("leave_status") or []:
                    uid = str(rec.get("userid") or "")
                    if uid in batch_records:
                        batch_records[uid].append(rec)
                if not result.get("has_more"):
                    break
                offset += LEAVE_STATUS_PAGE
        except DingTalkError as exc:
            logger.warning("请假记录批次拉取失败（%d 人）: %s", len(batch), exc)
            failed.extend(batch)
            continue
        out.update(batch_records)
    return out, failed


async def fetch_annual_quota(
    userid: str,
    annual_leave_code: str,
    *,
    client=None,
) -> Optional[Decimal]:
    """年假剩余天数。解析不出来返回 None——宁可不填也不填错。

    注意：该接口的响应形状在权限开通前无法实测（qyapi_holiday_readonly），
    按文档 `result.leave_quota` 解析；形状对不上就降级 None，年假余额留人工。
    """
    client = client or get_dingtalk_client()
    try:
        data = await client.post(
            "topapi/attendance/vacation/quota/list",
            json_data={"userid": userid, "leave_code": annual_leave_code},
        )
    except DingTalkError as exc:
        logger.warning("年假额度拉取失败 userid=%s: %s", userid, exc)
        return None
    quota = (data.get("result") or {}).get("leave_quota") or {}
    raw = quota.get("remain_quota") if isinstance(quota, dict) else None
    if raw is None:
        return None
    try:
        # remain_quota 按类型单位给百分数（percent_day 下 550 = 5.5 天）
        return Decimal(str(raw)) / Decimal("100")
    except (InvalidOperation, ValueError):
        return None


def split_leave(
    records: list[dict[str, Any]],
    type_map: dict[str, dict[str, str]],
    from_ms: int,
    to_ms: int,
    day_hours: Decimal,
) -> dict[str, Any]:
    """把一个人的请假记录聚成引擎要的四个数。纯函数。

    返回 personal_hours / sick_hours（小时）、annual_days（天）、
    unknown（未识别类型的 [(名称, 折算小时)]——报出来，不塞进任何扣款）。
    """
    personal_h = Decimal("0")
    sick_h = Decimal("0")
    annual_d = Decimal("0")
    unknown: list[dict[str, str]] = []
    window = max(to_ms - from_ms, 1)

    for rec in records or []:
        meta = type_map.get(str(rec.get("leave_code") or ""))
        try:
            duration = Decimal(str(rec.get("duration_percent") or "0")) / Decimal("100")
            start = int(rec.get("start_time") or 0)
            end = int(rec.get("end_time") or 0)
        except (InvalidOperation, ValueError, TypeError):
            continue
        # 跨月折算：只取与当月窗口重叠的时间占比
        overlap = max(0, min(end, to_ms) - max(start, from_ms))
        if end <= start or overlap <= 0:
            continue
        duration = duration * Decimal(overlap) / Decimal(end - start)

        unit = (meta or {}).get("unit") or str(rec.get("duration_unit") or "")
        name = (meta or {}).get("name") or ""
        if name == LEAVE_TYPE_ANNUAL:
            annual_d += duration if unit == "percent_day" else duration / day_hours
        elif name == LEAVE_TYPE_PERSONAL:
            personal_h += duration * day_hours if unit == "percent_day" else duration
        elif name == LEAVE_TYPE_SICK:
            sick_h += duration * day_hours if unit == "percent_day" else duration
        else:
            hours = duration * day_hours if unit == "percent_day" else duration
            unknown.append({"leave_name": name or str(rec.get("leave_code") or "?"),
                            "hours": str(hours.quantize(Decimal("0.01")))})

    return {
        "personal_hours": personal_h.quantize(Decimal("0.01")),
        "sick_hours": sick_h.quantize(Decimal("0.01")),
        "annual_days": annual_d.quantize(Decimal("0.01")),
        "unknown": unknown,
    }
