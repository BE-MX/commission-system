"""物流跟踪 — 运单软删除回归测试

Bug 背景（2026-07-10）：删除端点原先只置 is_active=False（轮询开关），
表内无软删字段、列表查询也不过滤 → 前端提示"已删除"但列表毫无变化，
删除已签收运单（is_active 本就是 0）时更是字面意义上的零变化。

本文件锁定修复口径：
- delete_shipment 置 deleted_at + 停轮询
- 已删运单对 列表/详情/统计/提交人 全部不可见
- 钉钉暂存重新提交同一运单 → 恢复可见（误删回退路径）
"""

from datetime import date, datetime

from app.tracking import shipment_service
from app.tracking.models import ShipmentStaging, ShipmentTracking, Waybill
from app.tracking.staging_service import scan_staging

SUPER_ADMIN = {"sub": "1", "username": "admin", "roles": ["super_admin"], "permissions": []}


def _mk_shipment(db, waybill_no="WB001", **kw):
    defaults = dict(
        waybill_no=waybill_no,
        carrier="FEDEX",
        carrier_name="联邦快递",
        current_status="in_transit",
        dingtalk_user_id="dt001",
        dingtalk_user_name="张三",
        is_active=True,
    )
    defaults.update(kw)
    shipment = ShipmentTracking(**defaults)
    db.add(shipment)
    db.flush()
    return shipment


class TestDeleteShipment:
    def test_delete_sets_deleted_at_and_stops_polling(self, db):
        s = _mk_shipment(db)
        assert shipment_service.delete_shipment(db, "WB001") is True
        assert s.deleted_at is not None
        assert not s.is_active

    def test_delete_missing_returns_false(self, db):
        assert shipment_service.delete_shipment(db, "NOPE") is False

    def test_delete_twice_returns_false(self, db):
        _mk_shipment(db)
        assert shipment_service.delete_shipment(db, "WB001") is True
        assert shipment_service.delete_shipment(db, "WB001") is False

    def test_delete_already_ended_shipment_disappears_from_list(self, db):
        # 原始 bug 场景：已签收运单 is_active 本就是 0，旧实现删除后零变化
        _mk_shipment(db, current_status="delivered", is_active=False)
        assert shipment_service.delete_shipment(db, "WB001") is True
        data = shipment_service.list_shipments(db, SUPER_ADMIN)
        assert data["total"] == 0


class TestDeletedInvisible:
    def test_list_excludes_deleted(self, db):
        _mk_shipment(db, "WB001")
        _mk_shipment(db, "WB002")
        shipment_service.delete_shipment(db, "WB001")
        data = shipment_service.list_shipments(db, SUPER_ADMIN)
        assert data["total"] == 1
        assert data["items"][0]["waybill_no"] == "WB002"

    def test_detail_returns_none_for_deleted(self, db):
        _mk_shipment(db)
        shipment_service.delete_shipment(db, "WB001")
        assert shipment_service.get_shipment_detail(db, "WB001") is None

    def test_stats_exclude_deleted(self, db):
        _mk_shipment(db, "WB001", current_status="in_transit")
        _mk_shipment(db, "WB002", current_status="delivered", is_active=False)
        shipment_service.delete_shipment(db, "WB001")
        stats = shipment_service.get_stats(db, SUPER_ADMIN)
        assert stats["total"] == 1
        assert stats["active"] == 0
        assert stats["in_transit"] == 0
        assert stats["delivered"] == 1

    def test_submitters_exclude_deleted_only_user(self, db):
        _mk_shipment(db, "WB001", dingtalk_user_name="张三")
        _mk_shipment(db, "WB002", dingtalk_user_name="李四")
        shipment_service.delete_shipment(db, "WB001")
        assert shipment_service.list_submitters(db) == ["李四"]


class TestStagingRestore:
    def _stage(self, db, waybill_no="WB001"):
        db.add(ShipmentStaging(
            waybill_no=waybill_no, carrier="FEDEX",
            dingtalk_user_id="dt001", dingtalk_user_name="张三",
        ))
        db.flush()

    async def test_resubmit_restores_deleted_shipment(self, db):
        s = _mk_shipment(db, current_status="in_transit", is_active=False)
        s.deleted_at = datetime.now()
        self._stage(db)
        stats = await scan_staging(db)
        assert stats["reactivated"] == 1
        assert s.deleted_at is None
        assert s.is_active
        assert s.poll_count == 0

    async def test_resubmit_restores_delivered_deleted_without_polling(self, db):
        # 已签收+已删除的运单重新提交 → 恢复可见，但不重启轮询
        s = _mk_shipment(db, current_status="delivered", is_active=False)
        s.deleted_at = datetime.now()
        self._stage(db)
        stats = await scan_staging(db)
        assert stats["reactivated"] == 1
        assert s.deleted_at is None
        assert not s.is_active


class TestOtherEntrances:
    async def test_refresh_single_excludes_deleted(self, db):
        from app.tracking.polling_service import refresh_single
        _mk_shipment(db)
        shipment_service.delete_shipment(db, "WB001")
        result = await refresh_single(db, "WB001")
        assert "error" in result

    def test_mcp_visible_scope_excludes_deleted(self, db):
        from app.mcp.tools import _visible_under_scope
        _mk_shipment(db)
        shipment_service.delete_shipment(db, "WB001")
        assert _visible_under_scope(db, SUPER_ADMIN, "WB001") is False

    async def test_reupload_restores_deleted_waybill(self, db, monkeypatch):
        # 录单来源的运单误删后重新录入 → 不 409，恢复可见并重置轮询计数
        from app.tracking import upload_service
        from app.tracking.schemas import WaybillCreate

        db.add(Waybill(
            waybill_no="WB001", carrier="FedEx", recipient_name="Alice",
            recipient_country="US", ship_date=date(2026, 7, 1),
            entry_source="manual", created_by="admin", created_at=datetime.now(),
        ))
        # carrier 与 payload 完全一致：SQLite 比较大小写敏感（MySQL utf8mb4 collation 不敏感）
        s = _mk_shipment(db, carrier="FedEx", is_active=False, consecutive_errors=10)
        s.deleted_at = datetime.now()
        db.flush()

        async def _fake_poll(_db, _shipment):
            return {"status": "ok"}

        async def _fake_push(*_a, **_k):
            return None

        monkeypatch.setattr(upload_service, "poll_single", _fake_poll)
        monkeypatch.setattr(upload_service, "_push_waybill_dingtalk", _fake_push)
        monkeypatch.setattr(upload_service, "generate_short_link", lambda _url: "https://s/x")

        payload = WaybillCreate(
            waybill_no="WB001", carrier="FedEx", recipient_name="Alice",
            recipient_country="US", ship_date=date(2026, 7, 1),
        )
        data = await upload_service.create_waybill_with_tracking(db, payload, SUPER_ADMIN)
        assert data["waybill_no"] == "WB001"
        assert s.deleted_at is None
        assert s.is_active
        assert s.consecutive_errors == 0
