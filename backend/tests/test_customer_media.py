"""客户拍摄素材交付：文件门禁、状态机、账号与客户隔离。"""

import asyncio
from datetime import date, datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.auth.models import (
    ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserExternalBinding,
)
from app.auth.service import seed_role_permissions
from app.auth.utils import hash_password
from app.core.database import get_db
from app.customer_media import service
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaBatch, CustomerPortalAccount,
)
from app.customer_media.public_router import PortalSecurityHeadersMiddleware, router as public_router
from app.customer_media.storage import LocalMediaStorage, MediaStorageError
from app.design.models import DesignDesigner, DesignScheduleRequest, DesignScheduleTask
from app.models.customer import CustomerCommissionSnapshot


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
    applicant, designer, _request, task = _seed_workflow(db)
    task.task_name = "客户可见系列名"
    task.shoot_type = "product"
    batch = service.get_or_create_batch(
        db, task.id, _payload(designer, "customer_media:write"),
    )
    batch.status = "published"
    batch.published_at = datetime(2026, 8, 17, 10, 30)
    db.commit()
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
        library = client.get("/api/customer-media/portal/library")
        assert library.status_code == 200
        assert library.json()["data"][0]["title"] == "客户可见系列名"
        assert library.json()["data"][0]["shoot_type"] == "product"


def test_internal_preview_signature_is_bound_to_asset(monkeypatch):
    monkeypatch.setattr(service.time, "time", lambda: 1_000)
    url = service.internal_preview_url(42, ttl_seconds=600)
    query = dict(item.split("=", 1) for item in url.split("?", 1)[1].split("&"))
    assert service.verify_internal_preview(42, int(query["expires"]), query["token"])
    assert not service.verify_internal_preview(43, int(query["expires"]), query["token"])
    portal_url = service.sales_portal_preview_url(42, ttl_seconds=600)
    portal_query = dict(
        item.split("=", 1) for item in portal_url.split("?", 1)[1].split("&")
    )
    assert "/sales-portal/assets/42/content" in portal_url
    assert service.verify_sales_portal_preview(
        42, int(portal_query["expires"]), portal_query["token"],
    )
    assert not service.verify_internal_preview(
        42, int(portal_query["expires"]), portal_query["token"],
    )
    monkeypatch.setattr(service.time, "time", lambda: 2_000)
    assert not service.verify_internal_preview(42, int(query["expires"]), query["token"])


def test_portal_page_permission_backfills_existing_sales_roles_once(db):
    role = ArkRole(name="sales_team", label="业务团队", is_system=False)
    source = ArkPermission(
        code="commission:self_read", module="commission", action="self_read",
        label="本人提成数据范围", kind="data", is_legacy=0, sort=10,
    )
    finance_role = ArkRole(name="finance_team", label="财务团队", is_system=False)
    finance_source = ArkPermission(
        code="commission_my:read", module="commission_my", action="read",
        label="个人提成页面", kind="page", is_legacy=0, sort=20,
    )
    db.add_all([role, source, finance_role, finance_source])
    db.flush()
    db.add_all([
        ArkRolePermission(role_id=role.id, permission_id=source.id),
        ArkRolePermission(role_id=finance_role.id, permission_id=finance_source.id),
    ])
    db.commit()

    seed_role_permissions(db)
    seed_role_permissions(db)

    portal_read = db.query(ArkPermission).filter_by(
        code="customer_media_portal:read",
    ).one()
    assert db.query(ArkRolePermission).filter_by(
        role_id=role.id, permission_id=portal_read.id,
    ).count() == 1
    portal_read_all = db.query(ArkPermission).filter_by(
        code="customer_media_portal:read_all",
    ).one()
    assert db.query(ArkRolePermission).filter_by(
        role_id=role.id, permission_id=portal_read_all.id,
    ).count() == 0

    assert db.query(ArkRolePermission).filter_by(
        role_id=finance_role.id, permission_id=portal_read.id,
    ).count() == 0


def test_sales_portal_preview_uses_current_customer_scope_and_published_content(db):
    _add_customer(db, "CUST-MEDIA-1", "客户甲")
    _add_customer(db, "CUST-MEDIA-2", "客户乙")
    applicant, designer, request, task = _seed_workflow(db)
    task.task_name = "新品系列拍摄"
    batch = service.get_or_create_batch(db, task.id, _payload(designer, "customer_media:write"))
    batch.status = "published"
    batch.published_at = datetime(2026, 8, 17, 10, 30)
    batch.updated_at = datetime(2026, 8, 17, 10, 30)
    db.add_all([
        CustomerMediaAsset(
            batch_id=batch.id, file_name="front.png", media_type="image",
            content_type="image/png", file_size=100, sha256="b" * 64,
            storage_provider="local", object_key="customers/front.png",
            uploaded_by=designer.id,
        ),
        CustomerMediaAsset(
            batch_id=batch.id, file_name="detail.mp4", media_type="video",
            content_type="video/mp4", file_size=200, sha256="c" * 64,
            storage_provider="local", object_key="customers/detail.mp4",
            uploaded_by=designer.id,
        ),
    ])
    draft_task = DesignScheduleTask(
        request_id=request.id, task_no="DT-MEDIA-DRAFT", designer_id=task.designer_id,
        task_name="未发布内部修订", customer_id="CUST-MEDIA-1", customer_name="客户甲",
        status="in_progress",
    )
    db.add(draft_task)
    db.flush()
    draft_batch = CustomerMediaBatch(
        task_id=draft_task.id, request_id=request.id,
        customer_id="CUST-MEDIA-1", customer_name_snapshot="客户甲",
        applicant_user_id=applicant.id, designer_user_id=designer.id,
        status="changes_requested", updated_at=datetime(2026, 8, 18, 9, 0),
    )
    db.add(draft_batch)
    db.flush()
    db.add(CustomerMediaAsset(
        batch_id=draft_batch.id, file_name="internal-only.png", media_type="image",
        content_type="image/png", file_size=999, sha256="d" * 64,
        storage_provider="local", object_key="customers/internal-only.png",
        uploaded_by=designer.id,
    ))
    admin = _payload(applicant, "customer_media:admin")
    account_a = service.create_portal_account(
        db, admin, "CUST-MEDIA-1", "client-a@example.com", "ClientPass123",
    )
    service.create_portal_account(
        db, admin, "CUST-MEDIA-2", "client-b@example.com", "ClientPass123",
    )
    db.add_all([
        ArkUserExternalBinding(
            ark_user_id=applicant.id, provider="okki", external_account_id="1007",
            binding_status="active", is_primary=True,
        ),
        CustomerCommissionSnapshot(
            customer_id="CUST-MEDIA-1", salesperson_id="1007",
            is_current=True, source="auto",
        ),
        CustomerCommissionSnapshot(
            customer_id="CUST-MEDIA-2", salesperson_id="1008",
            is_current=True, source="auto",
        ),
    ])
    db.commit()

    salesperson = _payload(applicant, "customer_media_portal:read")
    rows = service.list_sales_portal_customers(db, salesperson)
    assert [(row["customer_id"], row["status"], row["asset_count"]) for row in rows] == [
        ("CUST-MEDIA-1", "changes_requested", 2),
    ]
    assert rows[0]["updated_at"] == datetime(2026, 8, 17, 10, 30)
    detail = service.sales_portal_customer_detail(db, salesperson, "CUST-MEDIA-1")
    assert detail["customer"]["image_count"] == 1
    assert detail["customer"]["video_count"] == 1
    assert [row.id for row in detail["batches"]] == [batch.id]
    assert detail["task_meta"][task.id]["task_name"] == "新品系列拍摄"
    with pytest.raises(service.CustomerMediaNotFound, match="门户不存在"):
        service.sales_portal_customer_detail(db, salesperson, "CUST-MEDIA-2")

    supervisor = _payload(
        applicant, "customer_media_portal:read", "customer_media_portal:read_all",
    )
    assert {row["customer_id"] for row in service.list_sales_portal_customers(db, supervisor)} == {
        "CUST-MEDIA-1", "CUST-MEDIA-2",
    }

    assert service.sales_portal_asset(db, batch.assets[0].id).id == batch.assets[0].id
    account_a.is_active = False
    db.commit()
    disabled = service.sales_portal_customer_detail(db, salesperson, "CUST-MEDIA-1")
    assert disabled["customer"]["status"] == "disabled"
    assert disabled["batches"] == []
    with pytest.raises(service.CustomerMediaNotFound, match="已下架"):
        service.sales_portal_asset(db, batch.assets[0].id)

    account_a.is_active = True
    db.commit()

    batch.status = "unpublished"
    db.commit()
    with pytest.raises(service.CustomerMediaNotFound, match="已下架"):
        service.sales_portal_asset(db, batch.assets[0].id)
