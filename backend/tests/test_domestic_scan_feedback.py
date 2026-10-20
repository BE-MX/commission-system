"""Distinguish completed work from work waiting for upstream pieces."""

import pytest

from app.domestic import report_service, unit_service
from app.domestic.models import DomesticReportLog, DomesticSkipLog, DomesticSkipUnit
from app.production.models import UserProcessBinding
from tests.test_domestic_reporting import (
    _create_order, _item_of, _report, _steps, _user,
    craft_mapping, route, workers,
)


def test_quantity_rescan_reports_own_work_done_without_writing(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=1)["id"])
    _report(db, item, 0, workers[0], 1)
    _report(db, item, 1, workers[1], 1)
    before = db.query(DomesticReportLog).count()
    progress_id = _steps(db, item)[1]["progress_id"]

    for _ in range(2):
        view = report_service.scan_item(db, item.id, workers[1].id)
        assert view["can_submit"] is False
        assert view["block_reason"] == "OWN_STEPS_DONE"
        assert "已完成" in view["block_message"]
        assert "上一道" not in view["block_message"]
        assert view["next_step"] is None
    with pytest.raises(ValueError):
        report_service.submit_report(
            db, item_id=item.id, progress_id=progress_id,
            user_id=workers[1].id, qty=1, request_id="duplicate-fresh-request",
        )
    assert db.query(DomesticReportLog).count() == before
    assert _steps(db, item)[1]["completed_qty"] == 1
    assert _steps(db, item)[2]["completed_qty"] == 0


def test_partial_batch_still_waits_for_remaining_upstream(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=2)["id"])
    _report(db, item, 0, workers[0], 1)
    _report(db, item, 1, workers[1], 1)

    view = report_service.scan_item(db, item.id, workers[1].id)
    assert view["can_submit"] is False
    assert view["block_reason"] == "NOTHING_REPORTABLE"
    assert "上一道" in view["block_message"]


def test_unit_rescan_distinguishes_done_waiting_and_ready_pieces(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=3)["id"])
    units = unit_service.ensure_item_units(db, item)
    _report(db, item, 0, workers[0], 2)
    _report(db, item, 1, workers[1], 1)
    before = db.query(DomesticReportLog).count()

    done = report_service.scan_unit(db, units[0].id, workers[1].id)
    assert done["can_submit"] is False
    assert done["block_reason"] == "OWN_STEPS_DONE"
    assert "A1-01" in done["block_message"]
    assert "上一道" not in done["block_message"]
    assert done["next_step"] is None
    ready = report_service.scan_unit(db, units[1].id, workers[1].id)
    assert ready["can_submit"] is True
    assert ready["next_step"]["reportable_qty"] == 1
    waiting = report_service.scan_unit(db, units[2].id, workers[1].id)
    assert waiting["can_submit"] is False
    assert waiting["block_reason"] == "NOTHING_REPORTABLE"
    assert "上一道" in waiting["block_message"]
    assert "已报过" not in waiting["block_message"]
    assert db.query(DomesticReportLog).count() == before


def test_multiple_bindings_only_done_when_all_own_steps_done(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=1)["id"])
    units = unit_service.ensure_item_units(db, item)
    steps = _steps(db, item)
    db.add(UserProcessBinding(user_id=workers[0].id, process_id=steps[2]["process_id"]))
    db.flush()
    _report(db, item, 0, workers[0], 1)

    for view in [report_service.scan_item(db, item.id, workers[0].id),
                 report_service.scan_unit(db, units[0].id, workers[0].id)]:
        assert view["can_submit"] is False
        assert view["block_reason"] == "NOTHING_REPORTABLE"
    _report(db, item, 1, workers[1], 1)
    for view in [report_service.scan_item(db, item.id, workers[0].id),
                 report_service.scan_unit(db, units[0].id, workers[0].id)]:
        assert view["can_submit"] is True
        assert view["next_step"]["progress_id"] == steps[2]["progress_id"]


def test_revoked_work_can_be_scanned_again(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=1)["id"])
    unit = unit_service.ensure_item_units(db, item)[0]
    result = _report(db, item, 0, workers[0], 1)
    assert report_service.scan_item(db, item.id, workers[0].id)["block_reason"] == "OWN_STEPS_DONE"

    report_service.revoke_report(db, result["log_id"], workers[0].id)
    assert report_service.scan_item(db, item.id, workers[0].id)["can_submit"] is True
    assert report_service.scan_unit(db, unit.id, workers[0].id)["can_submit"] is True


def test_only_effective_skips_finish_own_work(db, craft_mapping, workers):
    item = _item_of(db, _create_order(db, workers[0], qty=1)["id"])
    unit = unit_service.ensure_item_units(db, item)[0]
    progress_id = _steps(db, item)[1]["progress_id"]
    skip = DomesticSkipLog(item_id=item.id, progress_id=progress_id, skip_qty=1,
                           source="decision", created_by_user_id=workers[0].id)
    db.add(skip)
    db.flush()
    db.add(DomesticSkipUnit(skip_log_id=skip.id, progress_id=progress_id, unit_id=unit.id))
    db.flush()

    # Decision skips recorded ahead of upstream completion do not yet count as passage.
    for view in [report_service.scan_item(db, item.id, workers[1].id),
                 report_service.scan_unit(db, unit.id, workers[1].id)]:
        assert view["block_reason"] == "NOTHING_REPORTABLE"
    _report(db, item, 0, workers[0], 1)
    for view in [report_service.scan_item(db, item.id, workers[1].id),
                 report_service.scan_unit(db, unit.id, workers[1].id)]:
        assert view["block_reason"] == "OWN_STEPS_DONE"
        assert "跳过" in view["block_message"]
        assert "已完成" not in view["block_message"]
