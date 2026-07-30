"""设计预约 — 改期/取消时同步不可用日期的生命周期

确认排期勾选 sync_unavailable 后，会以 reason="排期任务 {task_no}" 写入
design_unavailable_date；改期必须把这些行迁到新日期，取消必须释放。
（BUG 实案 2026-07-30：排期任务改期后，旧日期在不可用日历中仍显示为不可用）
"""

from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from app.design.models import (
    DesignScheduleRequest,
    DesignScheduleTask,
    DesignUnavailableDate,
)
from app.design.request_service import action_request
from app.design.schedule_service import reschedule_task
from app.design.schemas import DesignRequestAction, TaskReschedule


@pytest.fixture
def db(engine):
    """覆盖公共 db fixture：对齐生产 SessionLocal 的 autoflush=False"""
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


TASK_NO = "DT20260801001"
SYNC_REASON = f"排期任务 {TASK_NO}"


@pytest.fixture
def seed_task(db):
    """scheduled 状态的申请单 + 任务（计划 2026-08-03 ~ 08-05）"""
    req = DesignScheduleRequest(
        request_no="DR20260801001",
        customer_name="测试客户",
        salesperson_id=1,
        salesperson_name="业务员A",
        shoot_type="product",
        expect_start_date=date(2026, 8, 3),
        expect_end_date=date(2026, 8, 5),
        status="scheduled",
    )
    db.add(req)
    db.flush()
    task = DesignScheduleTask(
        request_id=req.id,
        task_no=TASK_NO,
        designer_id=1,
        status="scheduled",
        plan_start_date=date(2026, 8, 3),
        plan_start_period="am",
        plan_end_date=date(2026, 8, 5),
        plan_end_period="pm",
    )
    db.add(task)
    db.flush()
    return req, task


def _add_unavailable(db, d, reason, period=None):
    db.add(DesignUnavailableDate(date=d, period=period, reason=reason, created_by=1))


def _reschedule(db, task_id, start, end):
    return reschedule_task(
        db,
        task_id,
        TaskReschedule(plan_start_date=start, plan_end_date=end),
        operator_id=1,
        operator_name="管理员",
    )


class TestRescheduleMovesSyncedUnavailable:
    def test_old_dates_released_and_new_dates_marked(self, db, seed_task):
        _, task = seed_task
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)):
            _add_unavailable(db, d, SYNC_REASON)
        db.flush()

        _reschedule(db, task.id, date(2026, 8, 10), date(2026, 8, 11))

        rows = db.query(DesignUnavailableDate).all()
        assert {r.date for r in rows} == {date(2026, 8, 10), date(2026, 8, 11)}
        assert all(r.reason == SYNC_REASON for r in rows)

    def test_overlapping_move_keeps_overlap_dates(self, db, seed_task):
        """新旧区间重叠（8/3~8/5 → 8/4~8/6）：重叠日不得因先删后建的顺序丢失"""
        _, task = seed_task
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)):
            _add_unavailable(db, d, SYNC_REASON)
        db.flush()

        _reschedule(db, task.id, date(2026, 8, 4), date(2026, 8, 6))

        dates = {r.date for r in db.query(DesignUnavailableDate).all()}
        assert dates == {date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6)}

    def test_unsynced_task_stays_unsynced(self, db, seed_task):
        """确认时没勾 sync_unavailable 的任务，改期不能凭空创建不可用日期"""
        _, task = seed_task

        _reschedule(db, task.id, date(2026, 8, 10), date(2026, 8, 11))

        assert db.query(DesignUnavailableDate).count() == 0

    def test_manual_rows_untouched_and_not_duplicated(self, db, seed_task):
        """手工设置的不可用日期不被误删；新区间内已有的日期不重复建行"""
        _, task = seed_task
        _add_unavailable(db, date(2026, 8, 3), SYNC_REASON)
        _add_unavailable(db, date(2026, 8, 4), "团队会议")
        _add_unavailable(db, date(2026, 8, 10), "设备维护")
        db.flush()

        _reschedule(db, task.id, date(2026, 8, 10), date(2026, 8, 11))

        rows = {(r.date, r.reason) for r in db.query(DesignUnavailableDate).all()}
        assert rows == {
            (date(2026, 8, 4), "团队会议"),
            (date(2026, 8, 10), "设备维护"),
            (date(2026, 8, 11), SYNC_REASON),
        }


class TestRescheduleRejectsInvertedRange:
    def test_inverted_dates_rejected_and_rows_intact(self, db, seed_task):
        """结束早于开始必须拒绝，否则同步行会被删光且重建 0 行、不可恢复"""
        _, task = seed_task
        for d in (date(2026, 8, 3), date(2026, 8, 4)):
            _add_unavailable(db, d, SYNC_REASON)
        db.flush()

        with pytest.raises(ValueError, match="结束日期不能早于开始日期"):
            _reschedule(db, task.id, date(2026, 8, 12), date(2026, 8, 10))

        assert db.query(DesignUnavailableDate).count() == 2
        assert task.plan_start_date == date(2026, 8, 3)

    def test_same_day_pm_to_am_rejected(self, db, seed_task):
        _, task = seed_task
        with pytest.raises(ValueError, match="同一天内开始时段不能晚于结束时段"):
            reschedule_task(
                db,
                task.id,
                TaskReschedule(
                    plan_start_date=date(2026, 8, 10),
                    plan_start_period="pm",
                    plan_end_date=date(2026, 8, 10),
                    plan_end_period="am",
                ),
                operator_id=1,
                operator_name="管理员",
            )


class TestCancelReleasesSyncedUnavailable:
    def test_cancel_request_releases_task_dates(self, db, seed_task):
        req, task = seed_task
        _add_unavailable(db, date(2026, 8, 3), SYNC_REASON)
        _add_unavailable(db, date(2026, 8, 4), "团队会议")
        db.flush()

        action_request(
            db,
            req.id,
            DesignRequestAction(action="cancel", operator_role="design_staff"),
            operator_id=1,
            operator_name="管理员",
            operator_role="design_staff",
        )

        rows = db.query(DesignUnavailableDate).all()
        assert [(r.date, r.reason) for r in rows] == [(date(2026, 8, 4), "团队会议")]
        assert task.status == "cancelled"
