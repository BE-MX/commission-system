"""客户拍摄素材交付：文件门禁、状态机、账号与客户隔离。"""

import asyncio
from datetime import date
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.auth.models import ArkUser
from app.auth.utils import hash_password
from app.core.database import get_db
from app.customer_media import service
from app.customer_media.models import CustomerMediaAsset, CustomerPortalAccount
from app.customer_media.public_router import PortalSecurityHeadersMiddleware, router as public_router
from app.customer_media.storage import LocalMediaStorage, MediaStorageError
from app.design.models import DesignDesigner, DesignScheduleRequest, DesignScheduleTask


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 18), "gold").save(output, format="PNG")
    return output.getvalue()


def _add_customer(db, customer_id: str, name: str) -> None:
    db.connection().exec_driver_sql(
        "INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES (?, ?)",
        (customer_id, name),
    )


def _seed_workflow(db):
    applicant = ArkUser(
        username="media-applicant", password_hash=hash_password("Applicant123"),
        real_name="业务员", email="applicant@example.com",
    )
    designer_user = ArkUser(
        username="media-designer", password_hash=hash_password("Designer123"),
        real_name="设计师", email="designer@example.com",
    )
    db.add_all([applicant, designer_user])
    db.flush()
    designer = DesignDesigner(name="设计师", email="designer@example.com")
    db.add(designer)
    db.flush()
    request = DesignScheduleRequest(
        request_no="DR-MEDIA-001", customer_id="CUST-MEDIA-1", customer_name="客户甲",
        salesperson_id=applicant.id, salesperson_name=applicant.real_name,
        shoot_type="product", expect_start_date=date(2026, 8, 20),
        expect_end_date=date(2026, 8, 20), status="in_progress",
    )
    db.add(request)
    db.flush()
    task = DesignScheduleTask(
        request_id=request.id, task_no="DT-MEDIA-001", designer_id=designer.id,
        customer_id=request.customer_id, customer_name=request.customer_name,
        status="in_progress",
    )
    db.add(task)
    db.commit()
    return applicant, designer_user, request, task


def _payload(user, *permissions):
    return {"sub": str(user.id), "roles": [], "permissions": list(permissions)}


def test_local_storage_validates_real_format_and_path(tmp_path):
    storage = LocalMediaStorage(tmp_path)
    upload = UploadFile(BytesIO(_png()), filename='产品图 "A".png')
    stored = asyncio.run(storage.save_upload(
        upload, customer_id="CUST/../1", batch_id=7, max_bytes=1024 * 1024,
    ))

    assert stored.media_type == "image"
    assert (stored.width, stored.height) == (24, 18)
    assert storage.resolve(stored.object_key).read_bytes() == _png()
    assert ".." not in stored.object_key
    with pytest.raises(MediaStorageError, match="非法素材路径"):
        storage.resolve("../../etc/passwd")

    forged = UploadFile(BytesIO(b"not an image"), filename="forged.png")
    with pytest.raises(MediaStorageError, match="无法识别|真实格式"):
        asyncio.run(storage.save_upload(
            forged, customer_id="CUST1", batch_id=7, max_bytes=1024,
        ))
    assert not list(tmp_path.rglob("*.part"))


def test_submit_approve_publish_and_portal_customer_isolation(db):
    _add_customer(db, "CUST-MEDIA-1", "客户甲")
    _add_customer(db, "CUST-MEDIA-2", "客户乙")
    applicant, designer, _request, task = _seed_workflow(db)
    batch = service.get_or_create_batch(db, task.id, _payload(designer, "customer_media:write"))
    db.add(CustomerMediaAsset(
        batch_id=batch.id, file_name="approved.png", media_type="image",
        content_type="image/png", file_size=100, sha256="a" * 64,
        storage_provider="local", object_key="customers/a.png", uploaded_by=designer.id,
    ))
    db.commit()

    stale_version = batch.lock_version
    submitted = service.submit_batch(
        db, batch.id, _payload(designer, "customer_media:write"), stale_version,
    )
    assert submitted.status == "pending_review"
    assert task.status == "completed"
    with pytest.raises(service.CustomerMediaConflict, match="刷新后重试"):
        service.review_batch(
            db, batch.id, _payload(applicant, "customer_media:read"),
            "approve", None, stale_version,
        )

    published = service.review_batch(
        db, batch.id, _payload(applicant, "customer_media:read"),
        "approve", None, submitted.lock_version,
    )
    assert published.status == "published"
    assert [row.action for row in published.reviews] == ["submit", "approve"]

    admin = _payload(applicant, "customer_media:admin")
    account_a = service.create_portal_account(
        db, admin, "CUST-MEDIA-1", "client-a@example.com", "ClientPass123",
    )
    account_b = service.create_portal_account(
        db, admin, "CUST-MEDIA-2", "client-b@example.com", "ClientPass123",
    )
    assert [row.id for row in service.portal_library(db, account_a)] == [batch.id]
    assert service.portal_library(db, account_b) == []
    with pytest.raises(service.CustomerMediaNotFound):
        service.portal_asset(db, account_b, published.assets[0].id)

    # 数据库双唯一约束是并发创建时的最终防线：一客户单账号、邮箱也不可复用。
    db.add(CustomerPortalAccount(
        customer_id="CUST-MEDIA-1", customer_name_snapshot="客户甲",
        login_email="another@example.com", password_hash="x",
        created_by=applicant.id, updated_by=applicant.id,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_password_change_invalidates_existing_portal_session(db):
    _add_customer(db, "CUST-MEDIA-1", "客户甲")
    applicant, _designer, _request, _task = _seed_workflow(db)
    admin = _payload(applicant, "customer_media:admin")
    account = service.create_portal_account(
        db, admin, "CUST-MEDIA-1", "client@example.com", "ClientPass123",
    )
    _account, token, _expires = service.authenticate_portal(
        db, account.login_email, "ClientPass123", "127.0.0.1", "pytest", 30,
    )
    assert service.portal_session(db, token).id == account.id

    service.update_portal_account(
        db, admin, account.id, password="ChangedPass456",
    )
    with pytest.raises(service.CustomerMediaForbidden, match="登录已失效"):
        service.portal_session(db, token)


def test_public_portal_login_headers_and_uniform_failure(db):
    _add_customer(db, "CUST-MEDIA-1", "客户甲")
    applicant, _designer, _request, _task = _seed_workflow(db)
    service.create_portal_account(
        db, _payload(applicant, "customer_media:admin"), "CUST-MEDIA-1",
        "client@example.com", "ClientPass123",
    )
    app = FastAPI()
    app.add_middleware(PortalSecurityHeadersMiddleware)
    app.include_router(public_router, prefix="/api/customer-media/portal")
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as client:
        missing = client.get("/api/customer-media/portal/me")
        assert missing.status_code == 401
        assert missing.headers["cache-control"] == "private, no-store"
        unknown = client.post("/api/customer-media/portal/login", json={
            "email": "unknown@example.com", "password": "WrongPass123",
        })
        wrong = client.post("/api/customer-media/portal/login", json={
            "email": "client@example.com", "password": "WrongPass123",
        })
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json() == {"detail": "邮箱或密码错误"}
        success = client.post("/api/customer-media/portal/login", json={
            "email": "client@example.com", "password": "ClientPass123",
        })
        assert success.status_code == 200
        assert success.headers["cache-control"] == "private, no-store"
        assert client.get("/api/customer-media/portal/library").status_code == 200


def test_internal_preview_signature_is_bound_to_asset(monkeypatch):
    monkeypatch.setattr(service.time, "time", lambda: 1_000)
    url = service.internal_preview_url(42, ttl_seconds=600)
    query = dict(item.split("=", 1) for item in url.split("?", 1)[1].split("&"))
    assert service.verify_internal_preview(42, int(query["expires"]), query["token"])
    assert not service.verify_internal_preview(43, int(query["expires"]), query["token"])
    monkeypatch.setattr(service.time, "time", lambda: 2_000)
    assert not service.verify_internal_preview(42, int(query["expires"]), query["token"])
