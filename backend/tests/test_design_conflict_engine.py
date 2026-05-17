"""设计预约冲突检测引擎 — 单元测试

覆盖:
  - iter_slots / task_covers_slot 纯函数
  - check_conflict: 空 DB / 不可用时段 / 容量超载 / exclude_task_id 自排除
  - get_capacity_for_slot: 设置层级 fallback
"""

from datetime import date, timedelta

import pytest

from app.design.conflict_engine import (
    check_conflict,
    get_capacity_for_slot,
    iter_slots,
    task_covers_slot,
)
from app.design.models import (
    DesignCapacityConfig,
    DesignScheduleTask,
    DesignUnavailableDate,
)


# ── 纯函数 ─────────────────────────────────────────────

class TestPureSlotFunctions:
    def test_iter_slots_single_day_full(self):
        slots = list(iter_slots(date(2026, 5, 17), "am", date(2026, 5, 17), "pm"))
        assert slots == [(date(2026, 5, 17), "am"), (date(2026, 5, 17), "pm")]

    def test_iter_slots_single_half_day(self):
        slots = list(iter_slots(date(2026, 5, 17), "am", date(2026, 5, 17), "am"))
        assert slots == [(date(2026, 5, 17), "am")]

    def test_iter_slots_two_days_pm_to_am(self):
        slots = list(iter_slots(date(2026, 5, 17), "pm", date(2026, 5, 18), "am"))
        assert slots == [
            (date(2026, 5, 17), "pm"),
            (date(2026, 5, 18), "am"),
        ]

    def test_task_covers_slot_mid_range(self):
        task = type("T", (), {})()
        task.plan_start_date = date(2026, 5, 15)
        task.plan_start_period = "am"
        task.plan_end_date = date(2026, 5, 18)
        task.plan_end_period = "pm"
        assert task_covers_slot(task, date(2026, 5, 17), "am") is True
        assert task_covers_slot(task, date(2026, 5, 17), "pm") is True

    def test_task_covers_slot_outside_range(self):
        task = type("T", (), {})()
        task.plan_start_date = date(2026, 5, 15)
        task.plan_start_period = "am"
        task.plan_end_date = date(2026, 5, 16)
        task.plan_end_period = "pm"
        assert task_covers_slot(task, date(2026, 5, 17), "am") is False

    def test_task_covers_slot_missing_dates(self):
        task = type("T", (), {})()
        task.plan_start_date = None
        task.plan_end_date = None
        task.plan_start_period = "am"
        task.plan_end_period = "pm"
        assert task_covers_slot(task, date(2026, 5, 17), "am") is False


# ── DB 依赖 ─────────────────────────────────────────────

class TestCheckConflict:
    def test_empty_db_routes_to_pending_design(self, db, seed_designer):
        r = check_conflict(db, date(2026, 5, 17), date(2026, 5, 17),
                           start_period="am", end_period="pm")
        assert r["has_conflict"] is False
        assert r["route"] == "pending_design"
        assert r["overloaded_dates"] == []
        assert r["conflicting_unavailable_slots"] == []

    def test_full_day_unavailable_blocks_both_slots(self, db, seed_designer):
        db.add(DesignUnavailableDate(date=date(2026, 5, 17), period=None, reason="设计师休假"))
        db.flush()

        r = check_conflict(db, date(2026, 5, 17), date(2026, 5, 17),
                           start_period="am", end_period="pm")
        assert r["has_conflict"] is True
        assert r["route"] == "pending_audit"
        # 全天不可用应同时阻塞 am 和 pm 两个槽位
        blocked = {(s["date"], s["period"]) for s in r["conflicting_unavailable_slots"]}
        assert blocked == {("2026-05-17", "am"), ("2026-05-17", "pm")}

    def test_half_day_unavailable_blocks_only_specified_slot(self, db, seed_designer):
        db.add(DesignUnavailableDate(date=date(2026, 5, 17), period="am", reason="临时调休"))
        db.flush()

        r = check_conflict(db, date(2026, 5, 17), date(2026, 5, 17),
                           start_period="am", end_period="pm")
        assert r["has_conflict"] is True
        blocked = {(s["date"], s["period"]) for s in r["conflicting_unavailable_slots"]}
        assert blocked == {("2026-05-17", "am")}

    def test_capacity_overload_with_designer_specific_config(self, db, seed_designer):
        # 设容量 = 1,塞 1 个现有 task 占住,新预约应触发容量超载
        designer_id = seed_designer.id
        db.add(DesignCapacityConfig(
            config_date=date(2026, 5, 17), designer_id=designer_id, period="am",
            max_parallel_tasks=1,
        ))
        db.add(DesignScheduleTask(
            request_id=1, task_no="T-EXIST-1", designer_id=designer_id,
            plan_start_date=date(2026, 5, 17), plan_start_period="am",
            plan_end_date=date(2026, 5, 17), plan_end_period="am",
            status="scheduled",
        ))
        db.flush()

        r = check_conflict(db, date(2026, 5, 17), date(2026, 5, 17),
                           start_period="am", end_period="am",
                           designer_id=designer_id)
        assert r["has_conflict"] is True
        assert r["route"] == "pending_audit"
        assert len(r["overloaded_dates"]) == 1
        assert r["overloaded_dates"][0]["current_tasks"] == 1
        assert r["overloaded_dates"][0]["capacity"] == 1

    def test_exclude_task_id_treats_self_as_absent(self, db, seed_designer):
        # 容量 = 1,占用的就是被排除的那个 task — 预期不冲突(编辑已有 task 场景)
        designer_id = seed_designer.id
        existing = DesignScheduleTask(
            request_id=1, task_no="T-EDIT-1", designer_id=designer_id,
            plan_start_date=date(2026, 5, 17), plan_start_period="am",
            plan_end_date=date(2026, 5, 17), plan_end_period="am",
            status="scheduled",
        )
        db.add(existing)
        db.add(DesignCapacityConfig(
            config_date=date(2026, 5, 17), designer_id=designer_id, period="am",
            max_parallel_tasks=1,
        ))
        db.flush()

        r = check_conflict(db, date(2026, 5, 17), date(2026, 5, 17),
                           start_period="am", end_period="am",
                           designer_id=designer_id,
                           exclude_task_id=existing.id)
        assert r["has_conflict"] is False
        assert r["route"] == "pending_design"


# ── 容量 fallback 链 ──────────────────────────────────

class TestCapacityFallback:
    def test_default_capacity_when_no_config(self, db):
        """无任何配置时落到 settings.DESIGN_DEFAULT_DAILY_CAPACITY = 3"""
        cap = get_capacity_for_slot(db, date(2026, 5, 17), "am")
        assert cap == 3

    def test_global_config_overrides_default(self, db):
        db.add(DesignCapacityConfig(
            config_date=None, designer_id=None, period=None,
            max_parallel_tasks=5,
        ))
        db.flush()
        cap = get_capacity_for_slot(db, date(2026, 5, 17), "am")
        assert cap == 5

    def test_date_specific_config_overrides_global(self, db):
        db.add(DesignCapacityConfig(
            config_date=None, designer_id=None, period=None,
            max_parallel_tasks=5,
        ))
        db.add(DesignCapacityConfig(
            config_date=date(2026, 5, 17), designer_id=None, period="am",
            max_parallel_tasks=2,
        ))
        db.flush()
        cap = get_capacity_for_slot(db, date(2026, 5, 17), "am")
        assert cap == 2  # 更具体的配置优先
