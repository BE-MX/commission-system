"""发货检验模块测试：扫码验签 / 照片上传删除 / 提交幂等 / PC 列表与打印数据 / 读图鉴权

业务库两张出库表由 conftest engine fixture 以首选候选列名建在 lsordertest schema，
种子数据 2 单 3 明细（OB001: IT001/IT002，OB002: IT003）。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.mini.auth import create_mini_token
from app.shipping_inspection import qr_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto


def _user(db, username="inspector"):
    user = ArkUser(username=username, password_hash="x", real_name=username, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@contextmanager
def _pc_client(db, user, permissions):
    from app.shipping_inspection.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/shipping-inspection")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "real_name": user.real_name,
        "roles": [],
        "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@contextmanager
def _mini_client(db, user):
    from app.mini.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/mini")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_mini_token(user.id, "")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """照片落盘重定向到临时目录，不碰真实存储根。"""
    monkeypatch.setattr("app.shipping_inspection.file_service.storage_root", lambda: tmp_path)
    return tmp_path


def _qr(record_id="OB001"):
    return qr_service.generate_qr_data(record_id)


def _upload(client, record_id="OB001", item_id=None, name="photo.jpg"):
    data = {"outbound_record_id": record_id}
    if item_id:
        data["item_id"] = item_id
    return client.post(
        "/api/mini/shipping-inspection/photos",
        data=data,
        files={"file": (name, b"jpeg-bytes", "image/jpeg")},
    )


# ── 扫码验签 ──────────────────────────────────────────────


def test_scan_valid_code_returns_record_items_and_null_inspection(db):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": _qr("OB001")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["record"]["outbound_record_id"] == "OB001"
    assert body["record"]["outbound_no"] == "CK2026001"
    assert body["record"]["customer_name"] == "客户甲"
    assert [item["item_id"] for item in body["items"]] == ["IT001", "IT002"]
    assert body["items"][0]["qty"] == 10
    assert body["inspection"] is None
    assert body["photos"] == []


def test_scan_rejects_forged_sign(db):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": "ARK-I:OB001:deadbeef"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "SIGN_INVALID"


def test_scan_rejects_other_module_prefix(db):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": "ARK-D:1:abcd1234"})
    assert resp.status_code == 400


def test_scan_unknown_record_returns_400(db):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": _qr("OB999")})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RECORD_NOT_FOUND"


# ── 上传 / 删除照片 ───────────────────────────────────────


def test_upload_lazy_creates_draft_and_persists_file(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = _upload(client, item_id="IT001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] > 0
        assert (storage / body["file_path"]).is_file()

        scan = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": _qr("OB001")}).json()
    assert scan["inspection"]["status"] == "draft"
    assert scan["inspection"]["photo_count"] == 1
    assert scan["photos"][0]["item_id"] == "IT001"

    inspection = db.query(ShippingInspection).filter_by(outbound_record_id="OB001").one()
    assert inspection.status == "draft"
    assert inspection.outbound_no == "CK2026001"


def test_upload_multiple_photos_same_record_reuses_draft(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        first = _upload(client, item_id="IT001").json()
        second = _upload(client).json()
        scan = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": _qr("OB001")}).json()
    assert first["id"] != second["id"]
    assert scan["inspection"]["photo_count"] == 2
    assert db.query(ShippingInspection).filter_by(outbound_record_id="OB001").count() == 1


def test_upload_rejects_unknown_item_id(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = _upload(client, item_id="IT999")
    assert resp.status_code == 400
    assert "明细" in resp.json()["detail"]["message"]


def test_delete_photo_allowed_in_draft(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        photo = _upload(client).json()
        resp = client.delete(f"/api/mini/shipping-inspection/photos/{photo['id']}")
        assert resp.status_code == 200
        assert not (storage / photo["file_path"]).exists()
    assert db.query(ShippingInspectionPhoto).count() == 0


# ── 提交 ──────────────────────────────────────────────────


def test_submit_without_photos_rejected(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        resp = client.post("/api/mini/shipping-inspection/submit", json={
            "outbound_record_id": "OB001", "request_id": "req-0-photo",
        })
    assert resp.status_code == 400
    assert resp.json()["detail"]["message"] == "每个发货单至少上传一张照片"


def test_submit_success_then_idempotent_and_locked(db, storage):
    user = _user(db)
    with _mini_client(db, user) as client:
        _upload(client, item_id="IT001")
        _upload(client)

        submitted = client.post("/api/mini/shipping-inspection/submit", json={
            "outbound_record_id": "OB001", "request_id": "req-1", "remark": "外包装完好",
        })
        assert submitted.status_code == 200
        body = submitted.json()
        assert body["status"] == "submitted"
        assert body["photo_count"] == 2

        # 幂等：重复提交（不同 request_id）返回同一条单
        again = client.post("/api/mini/shipping-inspection/submit", json={
            "outbound_record_id": "OB001", "request_id": "req-2",
        })
        assert again.status_code == 200
        assert again.json()["id"] == body["id"]

        # 提交后再传照片 / 删照片都被拒
        assert _upload(client).status_code == 400
        photo_id = db.query(ShippingInspectionPhoto).first().id
        assert client.delete(f"/api/mini/shipping-inspection/photos/{photo_id}").status_code == 400

    inspection = db.query(ShippingInspection).filter_by(outbound_record_id="OB001").one()
    assert inspection.status == "submitted"
    assert inspection.photo_count == 2
    assert inspection.submitted_by == user.id
    assert inspection.submitted_at is not None
    assert inspection.remark == "外包装完好"


# ── PC 端 ─────────────────────────────────────────────────

_PC_PERMS = ["shipping_inspection:read", "shipping_inspection:write"]


def _submit_one(db, user, record_id="OB001", item_id="IT001"):
    with _mini_client(db, user) as client:
        _upload(client, record_id=record_id, item_id=item_id)
        client.post("/api/mini/shipping-inspection/submit", json={
            "outbound_record_id": record_id, "request_id": f"req-{record_id}",
        })


def test_pc_outbound_records_list_with_inspection_status(db, storage):
    user = _user(db)
    _submit_one(db, user)
    with _pc_client(db, user, _PC_PERMS) as client:
        resp = client.get("/api/shipping-inspection/outbound-records")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        by_id = {item["outbound_record_id"]: item for item in data["items"]}
        assert by_id["OB001"]["status"] == "submitted"
        assert by_id["OB001"]["photo_count"] == 1
        assert by_id["OB001"]["item_count"] == 2
        assert by_id["OB001"]["total_qty"] == 15
        assert by_id["OB002"]["status"] == "none"
        assert by_id["OB002"]["photo_count"] == 0

        # keyword / 日期筛选
        kw = client.get("/api/shipping-inspection/outbound-records", params={"keyword": "客户乙"}).json()["data"]
        assert kw["total"] == 1 and kw["items"][0]["outbound_record_id"] == "OB002"
        by_date = client.get(
            "/api/shipping-inspection/outbound-records",
            params={"date_from": "2026-08-21", "date_to": "2026-08-25"},
        ).json()["data"]
        assert by_date["total"] == 1 and by_date["items"][0]["outbound_record_id"] == "OB002"


def test_pc_outbound_records_require_permission(db):
    user = _user(db, "no-perm")
    with _pc_client(db, user, []) as client:
        assert client.get("/api/shipping-inspection/outbound-records").status_code == 403


def test_pc_print_data_contains_qr(db):
    user = _user(db)
    with _pc_client(db, user, ["shipping_inspection:read"]) as client:
        resp = client.get("/api/shipping-inspection/outbound-records/OB001/print-data")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["record"]["outbound_no"] == "CK2026001"
        assert len(data["items"]) == 2
        assert data["qr_code_base64"].startswith("data:image/png;base64,")
        # 二维码内容可通过本模块验签
        valid, record_id = qr_service.verify_qr_data(data["qr_data"])
        assert valid and record_id == "OB001"

        assert client.get("/api/shipping-inspection/outbound-records/OB999/print-data").status_code == 404


def test_pc_records_list_and_detail(db, storage):
    user = _user(db)
    _submit_one(db, user)
    with _pc_client(db, user, _PC_PERMS) as client:
        listing = client.get("/api/shipping-inspection/records").json()["data"]
        assert listing["total"] == 1
        row = listing["items"][0]
        assert row["outbound_no"] == "CK2026001"
        assert row["photo_count"] == 1
        assert row["submitted_by_name"] == user.real_name

        detail = client.get(f"/api/shipping-inspection/records/{row['id']}").json()["data"]
        assert detail["outbound_record_id"] == "OB001"
        assert [item["item_id"] for item in detail["items"]] == ["IT001", "IT002"]
        assert len(detail["photos"]) == 1
        assert detail["photos"][0]["item_id"] == "IT001"

        assert client.get("/api/shipping-inspection/records/99999").status_code == 404


def test_image_read_endpoints(db, storage):
    user = _user(db)
    with _mini_client(db, user) as mini:
        photo = _upload(mini).json()
        # mini 读图
        mini_img = mini.get(f"/api/mini/shipping-inspection/images/{photo['file_path']}")
        assert mini_img.status_code == 200
        assert mini_img.content == b"jpeg-bytes"

    with _pc_client(db, user, ["shipping_inspection:read"]) as client:
        pc_img = client.get(f"/api/shipping-inspection/images/{photo['file_path']}")
        assert pc_img.status_code == 200
        assert pc_img.content == b"jpeg-bytes"
        # 路径穿越被挡
        assert client.get("/api/shipping-inspection/images/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)

    # 无权限读图被拒
    with _pc_client(db, user, []) as client:
        assert client.get(f"/api/shipping-inspection/images/{photo['file_path']}").status_code == 403


# ── mini 端点响应形状契约 ─────────────────────────────────


def test_mini_endpoints_return_bare_dict_without_envelope(db, storage):
    """回归：mini 端点成功响应必须是裸业务 dict，不带 code/data 信封。

    小程序 check.js 按 mini 惯例直接消费响应体本身；若端点被改成 ok() 信封，
    扫码/上传/提交会在真机上全线误报失败（2026-09-01 对抗性审查 B1 的回归钉）。
    """
    user = _user(db)
    with _mini_client(db, user) as client:
        scan = client.post("/api/mini/shipping-inspection/scan", json={"qr_raw": _qr("OB001")})
        assert scan.status_code == 200
        assert "code" not in scan.json() and "data" not in scan.json()
        assert set(scan.json()) >= {"record", "items", "inspection", "photos"}

        up = _upload(client, "OB001")
        assert up.status_code == 200
        assert "code" not in up.json() and "data" not in up.json()
        assert set(up.json()) >= {"id", "file_path"}

        sub = client.post(
            "/api/mini/shipping-inspection/submit",
            json={"outbound_record_id": "OB001", "request_id": "r1"},
        )
        assert sub.status_code == 200
        assert "code" not in sub.json() and "data" not in sub.json()
        assert sub.json()["status"] == "submitted"
