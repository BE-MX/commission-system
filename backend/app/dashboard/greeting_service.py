"""工作台 AI 问候 — 每日一句的生成、缓存与降级

数据流：
  前端汇总实时上下文（日期/星期/节日/待办计数） → POST /api/dashboard/greeting
  → 本模块组 prompt 走 app.ai.service facade 调模型 → 净化为单行文案返回。

降级链（任何一环失败都不让工作台开天窗）：
  进程内按 (user_id, date) 缓存 → AI 调用失败 → 规则模板兜底（source=fallback）
  → 前端另有本地 daily-tips 兜底（请求本身失败时）。

preset 解析：优先专用预设 dashboard_greeting（后台可配，宪法 7「preset 后台可配」），
没有则退到任意一个「启用中 + direct provider 启用中」的预设——问候是自由文本生成，
不依赖特定模型，preset 的 system_prompt 会被我们的任务指令覆盖（指令放在 user message
末尾，最新指令优先）。
"""

from __future__ import annotations

import logging
import time
import zlib
from datetime import date as date_type

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider
from app.ai.service import chat
from app.dashboard.schemas import GreetingRequest

logger = logging.getLogger("commission")

PREFERRED_PRESET = "dashboard_greeting"
MAX_TEXT_LEN = 120

# (user_id, date) → {"text": ..., "source": ...}；问候一天只生成一次（refresh 除外）
# 注意：进程内缓存，多 worker 部署时各自独立（同日可能不同文案，业务可接受）
_CACHE: dict[tuple[int, str], dict] = {}
_CACHE_CAP = 2000

# refresh 直达付费模型，必须有限流：同一用户 60s 内的重复刷新按普通请求处理（吃缓存）
_REFRESH_TS: dict[int, float] = {}
REFRESH_COOLDOWN_SEC = 60

_STYLES = ["鼓励", "小确幸", "冷幽默", "打工人梗"]


def _stable_hash(text: str) -> int:
    """跨进程稳定的散列（str 的 hash() 受 PYTHONHASHSEED 影响，重启即变）。"""
    return zlib.crc32(text.encode("utf-8"))


def _preset_usable(db: Session, preset: AiPreset | None) -> bool:
    """预设本身启用还不够，provider 必须是启用中的直连类型（chat 对 accio_work 会 raise）。"""
    if preset is None:
        return False
    provider = (
        db.query(AiProvider)
        .filter(AiProvider.id == preset.provider_id, AiProvider.deleted_at.is_(None))
        .first()
    )
    return bool(
        provider
        and provider.is_enabled
        and provider.provider_type == "direct"
    )


def _candidate_presets(db: Session) -> list[AiPreset]:
    """候选预设：专用预设优先，其余直连可用预设按序兜底（去重 provider，最多 3 个）。"""
    candidates: list[AiPreset] = []
    preferred = (
        db.query(AiPreset)
        .filter(
            AiPreset.preset_name == PREFERRED_PRESET,
            AiPreset.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
        )
        .first()
    )
    if _preset_usable(db, preferred):
        candidates.append(preferred)
    others = (
        db.query(AiPreset)
        .join(AiProvider, AiProvider.id == AiPreset.provider_id)
        .filter(
            AiPreset.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
            AiProvider.deleted_at.is_(None),
            AiProvider.is_enabled.is_(True),
            AiProvider.provider_type == "direct",
        )
        .order_by(AiPreset.id)
        .limit(10)
        .all()
    )
    seen_providers = {c.provider_id for c in candidates}
    for preset in others:
        if len(candidates) >= 3:
            break
        if preset.provider_id in seen_providers:
            continue
        seen_providers.add(preset.provider_id)
        candidates.append(preset)
    return candidates


def _build_prompt(payload: GreetingRequest, user_name: str) -> list[dict]:
    ctx = payload.context
    style = _STYLES[(_stable_hash(ctx.date) % len(_STYLES))]

    lines = [
        f"今天是 {ctx.date}，{ctx.weekday}，{ctx.period}。",
        f"对方叫「{user_name}」，是外贸公司的员工，刚打开内部工作台。",
    ]
    if ctx.holidays_today:
        lines.append(f"今天放假的客户国家/地区：{'、'.join(ctx.holidays_today)}。")
    if ctx.upcoming_holidays:
        lines.append(f"近期的海外节日：{'、'.join(ctx.upcoming_holidays)}。")
    busy = [f"{label}{count}件" for label, count in ctx.pending.items() if count > 0]
    if busy:
        lines.append(f"TA 今天待处理：{'，'.join(busy)}。")

    lines.append(
        f"请写一句开工问候，风格「{style}」。要求："
        "一两句话，80字以内；可以自然地引用上面的节日或待办信息，但不必全用；"
        "像贴心的AI工作助理说话，不要套话鸡汤；直接输出问候正文，"
        "不要称呼、不要引号、不要解释、不要emoji以外的符号装饰。"
    )
    return [{"role": "user", "content": "\n".join(lines)}]


def _sanitize(text: str) -> str:
    """模型输出净化为单行：去引号/换行，超长截断。"""
    cleaned = " ".join(str(text or "").split())
    cleaned = cleaned.strip('"“”\' ')
    return cleaned[:MAX_TEXT_LEN]


def _fallback(payload: GreetingRequest, user_name: str) -> str:
    """规则模板兜底——AI 未配置/失败时也不开天窗。"""
    ctx = payload.context
    pool: list[str] = []
    if ctx.holidays_today:
        pool.append(f"今天{'、'.join(ctx.holidays_today[:2])}的客户在放假，正是整理内务、弯道超车的好日子。")
    if ctx.upcoming_holidays:
        pool.append(f"小提醒：{ctx.upcoming_holidays[0]}，要催的款、要确认的单，趁早发出去。")
    busy = [f"{label}{count}件" for label, count in ctx.pending.items() if count > 0]
    if busy:
        pool.append(f"今天有{'、'.join(busy[:2])}等着你，一件件来，你搞得定。")
    pool += [
        f"{ctx.weekday}好，{user_name}。咖啡续上，单子在路上。",
        "今天的目标：把待办清零，把烦恼留给昨天。",
        "别慌，运单在跑，客户在回，一切都会准时。",
    ]
    # 同日同人稳定同一句，避免刷新跳变
    return pool[_stable_hash(f"{ctx.date}:{user_name}") % len(pool)]


def get_greeting(
    db: Session,
    user_id: int,
    user_name: str,
    payload: GreetingRequest,
) -> dict:
    cache_key = (user_id, payload.context.date or date_type.today().isoformat())
    cached = _CACHE.get(cache_key)
    if payload.refresh:
        # 冷却期内的 refresh 降级为普通请求（吃缓存），防滥刷付费模型
        if cached is not None and time.monotonic() - _REFRESH_TS.get(user_id, 0.0) < REFRESH_COOLDOWN_SEC:
            return cached
        if len(_REFRESH_TS) >= _CACHE_CAP:
            _REFRESH_TS.clear()
        _REFRESH_TS[user_id] = time.monotonic()
    elif cached is not None:
        return cached

    result: dict | None = None
    for preset in _candidate_presets(db):
        try:
            resp = chat(
                db,
                preset.preset_name,
                _build_prompt(payload, user_name),
                caller_module="dashboard",
                caller_user_id=user_id,
                snapshot_mode="metadata",
            )
            text = _sanitize(resp.get("content"))
            if text:
                result = {"text": text, "source": "ai"}
                break
        except Exception as exc:
            # 硬约定 6：不无声吞——记日志 + NSSM 可见的 print，然后试下一个/走兜底
            logger.warning(
                "dashboard greeting AI failed (preset=%s): %s",
                preset.preset_name, type(exc).__name__,
            )
            print(f"[dashboard] greeting AI failed: {type(exc).__name__}", flush=True)

    if result is None:
        result = {"text": _fallback(payload, user_name), "source": "fallback"}
    result["date"] = cache_key[1]

    if len(_CACHE) >= _CACHE_CAP:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result
