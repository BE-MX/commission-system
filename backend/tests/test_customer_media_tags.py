"""客户素材客户标签：scope 隔离 / 匹配 / 幂等新建 / 打标权限 / 门户筛选与隔离。"""

import asyncio
from datetime import date, datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.datastructures import UploadFile

from app.asset import tag_service
from app.asset.folder_upload_service import validate_folder_tags
from app.asset.models import TagDimension, TagValue
from app.asset.router import router as asset_router
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import hash_password
from app.core.database import get_db
from app.customer_media import service
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaAssetTag, CustomerMediaBatch, CustomerMediaCustomerTag,
)
from app.customer_media.public_router import router as public_router
from app.customer_media.router import router as internal_router
from app.customer_media.storage import LocalMediaStorage
from app.design.models import DesignDesigner, DesignScheduleRequest, DesignScheduleTask
from app.models.customer import CustomerCommissionSnapshot


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 18), "gold").save(output, format="PNG")
    return output.getvalue()


def _upload_png(name="asset.png"):
    return UploadFile(BytesIO(_png()), filename=name)


def _add_customer(db, customer_id: str, name: str) -> None:
    db.connection().exec_driver_sql(
        "INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES (?, ?)",
        (customer_id, name),
    )


def _seed_workflow(db):
    applicant = ArkUser(
        username="tag-applicant", password_hash=hash_password("Applicant123"),
        real_name="业务员", email="tag-applicant@example.com",
    )
    designer_user = ArkUser(
        username="tag-designer", password_hash=hash_password("Designer123"),
        real_name="设计师", email="tag-designer@example.com",
    )
    outsider = ArkUser(
        username="tag-outsider", password_hash=hash_password("Outsider123"),
        real_name="路人", email="tag-outsider@example.com",
    )
    db.add_all([applicant, designer_user, outsider])
    db.flush()
    designer = DesignDesigner(name="设计师", email="tag-designer@example.com")
    db.add(designer)
    db.flush()
    request = DesignScheduleRequest(
        request_no="DR-TAG-001", customer_id="CUST-TAG-1", customer_name="标签客户甲",
        salesperson_id=applicant.id, salesperson_name=applicant.real_name,
        shoot_type="product", expect_start_date=date(2026, 9, 1),
        expect_end_date=date(2026, 9, 1), status="in_progress",
    )
    db.add(request)
    db.flush()
    task = DesignScheduleTask(
        request_id=request.id, task_no="DT-TAG-001", designer_id=designer.id,
        customer_id=request.customer_id, customer_name=request.customer_name,
        status="in_progress",
    )
    db.add(task)
    db.commit()
    return applicant, designer_user, outsider, request, task


def _payload(user, *permissions):
    return {"sub": str(user.id), "roles": [], "permissions": list(permissions)}


def _make_dim(db, name, label, *, scope="customer", single=0, values=(), visible=1):
    dim = TagDimension(
        name=name, label=label, is_single_select=single, is_visible=visible,
        is_managed=0, tag_scope=scope,
    )
    db.add(dim)
    db.flush()
    created = []
    for value in values:
        tv = TagValue(dimension_id=dim.id, value=value, is_active=1)
        db.add(tv)
        created.append(tv)
    db.flush()
    return dim, created


def _tag_rows(db, asset_id):
    return db.query(CustomerMediaAssetTag).filter_by(asset_id=asset_id).all()


# ── scope 隔离 ──────────────────────────────────────────

def test_customer_scope_isolated_from_internal_validate_and_dimensions(db):
    internal_dim, _ = _make_dim(db, "internal_style", "内部风格", scope="internal", values=["白底图"])
    customer_dim, _ = _make_dim(db, "customer_scene", "客户场景", values=["场景图"])
    db.commit()

    # 默认 internal：客户标签不参与素材库匹配；反之亦然
    assert validate_folder_tags(db, ["场景图"]).missing == ["场景图"]
    result = validate_folder_tags(db, ["场景图"], scope="customer")
    assert result.matched[0]["dimension_id"] == customer_dim.id
    assert validate_folder_tags(db, ["白底图"], scope="customer").missing == ["白底图"]

    tag_service.invalidate_dim_cache()
    internal_dims = tag_service.list_dimensions_cached(db)
    assert {d["name"] for d in internal_dims} == {"internal_style"}
    assert all(d["tag_scope"] == "internal" for d in internal_dims)
    customer_dims = tag_service.list_dimensions_cached(db, "customer")
    assert {d["name"] for d in customer_dims} == {"customer_scene"}
    # 两个 scope 分槽互不影响
    assert {d["name"] for d in tag_service.list_dimensions_cached(db)} == {"internal_style"}
    tag_service.invalidate_dim_cache()

    # 素材库默认 dimensions 列表（asset 路由，scope 默认 internal）不出客户维度
    app = FastAPI()
    app.include_router(asset_router, prefix="/api/assets")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "roles": [], "permissions": ["asset:read", "asset:admin"],
    }
    with TestClient(app) as client:
        default = client.get("/api/assets/tags/dimensions")
        assert default.status_code == 200
        assert {d["name"] for d in default.json()["data"]} == {"internal_style"}
        scoped = client.get("/api/assets/tags/dimensions", params={"scope": "customer"})
        assert {d["name"] for d in scoped.json()["data"]} == {"customer_scene"}
    tag_service.invalidate_dim_cache()


def test_validate_hit_missing_ambiguous(db):
    dim_a, _ = _make_dim(db, "cust_a", "客户维度A", values=["礼盒", "白底图"])
    dim_b, _ = _make_dim(db, "cust_b", "客户维度B", values=["礼盒"])
    db.commit()

    result = service.validate_tags(db, ["白底图", "礼盒", "不存在的标签xyz"])
    assert [(m["tag_name"], m["dimension_id"]) for m in result.matched] == [("白底图", dim_a.id)]
    assert result.ambiguous[0]["tag_name"] == "礼盒"
    assert {d["dimension_id"] for d in result.ambiguous[0]["dimensions"]} == {dim_a.id, dim_b.id}
    assert result.missing == ["不存在的标签xyz"]
    assert result.is_valid is False


def test_resolve_idempotent_reuses_value_and_rejects_internal_dim(db):
    customer_dim, _ = _make_dim(db, "customer_general", "客户标签")
    internal_dim, _ = _make_dim(db, "internal_only", "内部专用", scope="internal")
    db.commit()
    _applicant, designer, _outsider, _request, _task = _seed_workflow(db)
    writer = _payload(designer, "customer_media:write")

    mapping = service.resolve_auto_create_tags(db, writer, {"新场景": customer_dim.id})
    entry = mapping["新场景"]
    assert entry["created"] is True
    assert entry["dimension_id"] == customer_dim.id

    again = service.resolve_auto_create_tags(db, writer, {"新场景": customer_dim.id})
    assert again["新场景"]["created"] is False
    assert again["新场景"]["tag_value_id"] == entry["tag_value_id"]
    assert db.query(TagValue).filter_by(dimension_id=customer_dim.id, value="新场景").count() == 1

    with pytest.raises(service.CustomerMediaError, match="标签使用域"):
        service.resolve_auto_create_tags(db, writer, {"越域": internal_dim.id})


def test_create_customer_tag_value_reuses_same_name(db):
    customer_dim, _ = _make_dim(db, "customer_general", "客户标签")
    internal_dim, _ = _make_dim(db, "internal_only", "内部专用", scope="internal")
    db.commit()
    _applicant, designer, _outsider, _request, _task = _seed_workflow(db)
    writer = _payload(designer, "customer_media:write")

    created = service.create_customer_tag_value(db, writer, customer_dim.id, " 白底图 ")
    assert created["created"] is True
    reused = service.create_customer_tag_value(db, writer, customer_dim.id, "白底图")
    assert reused["created"] is False and reused["id"] == created["id"]
    with pytest.raises(service.CustomerMediaNotFound):
        service.create_customer_tag_value(db, writer, internal_dim.id, "内部标签")


# ── 上传打标与标签编辑 ───────────────────────────────────

def _seed_batch_with_asset(db):
    """一个 draft 批次 + 一个直接入库的素材。"""
    _add_customer(db, "CUST-TAG-1", "标签客户甲")
    applicant, designer, outsider, _request, task = _seed_workflow(db)
    batch = service.get_or_create_batch(db, task.id, _payload(designer, "customer_media:write"))
    asset = CustomerMediaAsset(
        batch_id=batch.id, file_name="front.png", media_type="image",
        content_type="image/png", file_size=100, sha256="t" * 64,
        storage_provider="local", object_key="customers/tag-front.png",
        uploaded_by=designer.id,
    )
    db.add(asset)
    db.commit()
    return applicant, designer, outsider, batch, asset


def test_upload_with_tags_json_persists_and_rejects_bad_scope(db, tmp_path, monkeypatch):
    customer_dim, values = _make_dim(db, "customer_general", "客户标签", values=["白底图", "场景图"])
    internal_dim, internal_values = _make_dim(db, "internal_only", "内部专用", scope="internal", values=["内部图"])
    applicant, designer, outsider, batch, _asset = _seed_batch_with_asset(db)
    writer = _payload(designer, "customer_media:write")
    monkeypatch.setattr(
        service, "storage_for", lambda provider="local": LocalMediaStorage(tmp_path),
    )

    updated = asyncio.run(service.upload_asset(
        db, batch.id, writer, _upload_png("tagged.png"),
        tags=[{"dimension_id": customer_dim.id, "tag_value_ids": [v.id for v in values]}],
    ))
    uploaded = next(a for a in updated.assets if a.file_name == "tagged.png")
    rows = _tag_rows(db, uploaded.id)
    assert {(row.dimension_id, row.tag_value_id) for row in rows} == {
        (customer_dim.id, v.id) for v in values
    }

    with pytest.raises(service.CustomerMediaError, match="客户标签维度"):
        asyncio.run(service.upload_asset(
            db, batch.id, writer, _upload_png("bad.png"),
            tags=[{"dimension_id": internal_dim.id, "tag_value_ids": [internal_values[0].id]}],
        ))
    assert db.query(CustomerMediaAsset).filter_by(file_name="bad.png").count() == 0


def test_customer_labels_survive_new_booking_and_upload_requires_label(db, tmp_path, monkeypatch):
    dim, values = _make_dim(db, "customer_series", "客户系列", values=["春季", "夏季"])
    _add_customer(db, "CUST-TAG-1", "标签客户甲")
    applicant, designer, _outsider, first_request, first_task = _seed_workflow(db)
    salesperson = _payload(applicant, "design:write")
    writer = _payload(designer, "customer_media:write")
    spring = [{"dimension_id": dim.id, "tag_value_ids": [values[0].id]}]
    summer = [{"dimension_id": dim.id, "tag_value_ids": [values[1].id]}]
    assert service.add_customer_tags(db, first_request.customer_id, salesperson, spring)[0]["value"] == "春季"
    assert service.add_customer_tags(db, first_request.customer_id, salesperson, spring) == service.list_customer_tags(db, first_request.customer_id)

    second_request = DesignScheduleRequest(
        request_no="DR-TAG-002", customer_id=first_request.customer_id,
        customer_name=first_request.customer_name, salesperson_id=applicant.id,
        salesperson_name=applicant.real_name, shoot_type="product",
        expect_start_date=date(2026, 9, 2), expect_end_date=date(2026, 9, 2),
        status="in_progress",
    )
    db.add(second_request)
    db.flush()
    second_task = DesignScheduleTask(
        request_id=second_request.id, task_no="DT-TAG-002", designer_id=first_task.designer_id,
        customer_id=first_request.customer_id, customer_name=first_request.customer_name,
        status="in_progress",
    )
    db.add(second_task)
    db.commit()
    assert service.task_customer_id(db, second_task.id, writer) == first_request.customer_id
    assert [tag["value"] for tag in service.list_customer_tags(db, second_request.customer_id)] == ["春季"]

    service.add_customer_tags(db, second_request.customer_id, writer, summer)
    assert {tag["value"] for tag in service.list_customer_tags(db, first_request.customer_id)} == {"春季", "夏季"}
    assert db.query(CustomerMediaCustomerTag).filter_by(customer_id=first_request.customer_id).count() == 2

    batch = service.get_or_create_batch(db, second_task.id, writer)
    monkeypatch.setattr(service, "storage_for", lambda provider="local": LocalMediaStorage(tmp_path))
    with pytest.raises(service.CustomerMediaError, match="至少一个客户标签"):
        asyncio.run(service.upload_asset(db, batch.id, writer, _upload_png("untagged.png")))
    assert list(tmp_path.rglob("*.png")) == []
    updated = asyncio.run(service.upload_asset(db, batch.id, writer, _upload_png("summer.png"), tags=summer))
    uploaded = next(asset for asset in updated.assets if asset.file_name == "summer.png")
    assert [(tag.dimension_id, tag.tag_value_id) for tag in _tag_rows(db, uploaded.id)] == [(dim.id, values[1].id)]


def test_update_asset_tags_permission_and_dimension_overwrite(db):
    customer_dim, values = _make_dim(db, "customer_general", "客户标签", values=["白底图", "场景图"])
    other_dim, other_values = _make_dim(db, "customer_series", "客户系列", values=["夏季"])
    applicant, designer, outsider, batch, asset = _seed_batch_with_asset(db)

    # 非发起人非 admin → 403
    with pytest.raises(service.CustomerMediaForbidden, match="预约发起人"):
        service.update_asset_tags(
            db, batch.id, asset.id, _payload(outsider, "customer_media:read"),
            [{"dimension_id": customer_dim.id, "tag_value_ids": [values[0].id]}],
        )
    assert _tag_rows(db, asset.id) == []

    reviewer = _payload(applicant, "customer_media:read")
    service.update_asset_tags(
        db, batch.id, asset.id, reviewer,
        [
            {"dimension_id": customer_dim.id, "tag_value_ids": [values[0].id]},
            {"dimension_id": other_dim.id, "tag_value_ids": [other_values[0].id]},
        ],
    )
    assert {(r.dimension_id, r.tag_value_id) for r in _tag_rows(db, asset.id)} == {
        (customer_dim.id, values[0].id), (other_dim.id, other_values[0].id),
    }

    # 按维度全量覆盖：出现的维度被替换/清空，未出现的维度不动
    service.update_asset_tags(
        db, batch.id, asset.id, reviewer,
        [{"dimension_id": customer_dim.id, "tag_value_ids": [values[1].id]}],
    )
    assert {(r.dimension_id, r.tag_value_id) for r in _tag_rows(db, asset.id)} == {
        (customer_dim.id, values[1].id), (other_dim.id, other_values[0].id),
    }
    service.update_asset_tags(
        db, batch.id, asset.id, reviewer,
        [{"dimension_id": customer_dim.id, "tag_value_ids": []}],
    )
    assert {(r.dimension_id, r.tag_value_id) for r in _tag_rows(db, asset.id)} == {
        (other_dim.id, other_values[0].id),
    }

    # admin 也可编辑
    admin = _payload(outsider, "customer_media:admin")
    service.update_asset_tags(
        db, batch.id, asset.id, admin,
        [{"dimension_id": customer_dim.id, "tag_value_ids": [values[0].id]}],
    )
    assert {(r.dimension_id, r.tag_value_id) for r in _tag_rows(db, asset.id)} == {
        (other_dim.id, other_values[0].id), (customer_dim.id, values[0].id),
    }
    # 审计留痕
    actions = [row.action for row in db.query(CustomerMediaBatch).get(batch.id).reviews]
    assert "update_tags" in actions


def test_update_asset_tags_rejects_single_select_multi_and_internal_dim(db):
    single_dim, single_values = _make_dim(
        db, "customer_single", "客户单选", single=1, values=["A", "B"],
    )
    internal_dim, internal_values = _make_dim(db, "internal_only", "内部专用", scope="internal", values=["X"])
    _applicant, _designer, _outsider, batch, asset = _seed_batch_with_asset(db)
    reviewer = _payload(_applicant, "customer_media:read")

    with pytest.raises(service.CustomerMediaError, match="单选"):
        service.update_asset_tags(
            db, batch.id, asset.id, reviewer,
            [{"dimension_id": single_dim.id, "tag_value_ids": [v.id for v in single_values]}],
        )
    with pytest.raises(service.CustomerMediaError, match="客户标签维度"):
        service.update_asset_tags(
            db, batch.id, asset.id, reviewer,
            [{"dimension_id": internal_dim.id, "tag_value_ids": [internal_values[0].id]}],
        )
    with pytest.raises(service.CustomerMediaError, match="不属于所选维度"):
        service.update_asset_tags(
            db, batch.id, asset.id, reviewer,
            [{"dimension_id": single_dim.id, "tag_value_ids": [internal_values[0].id]}],
        )
    assert _tag_rows(db, asset.id) == []


# ── HTTP 层：内部端点权限与响应 ───────────────────────────

def _internal_app(db, payload):
    app = FastAPI()
    app.include_router(internal_router, prefix="/api/customer-media")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: payload
    return app


def test_booking_and_designer_customer_tag_endpoints_share_customer_labels(db):
    dim, values = _make_dim(db, "customer_use", "用途", values=["白底", "场景"])
    applicant, designer, outsider, batch, _asset = _seed_batch_with_asset(db)
    db.connection().exec_driver_sql(
        "UPDATE lsordertest.customer_info SET owner_user_ids = ? WHERE company_id = ?",
        ('[1007]', 'CUST-TAG-1'),
    )
    db.add_all([
        ArkUserExternalBinding(
            ark_user_id=applicant.id, provider="okki", external_account_id="1007",
            binding_status="active", is_primary=True,
        ),
        ArkUserExternalBinding(
            ark_user_id=outsider.id, provider="okki", external_account_id="1008",
            binding_status="active", is_primary=True,
        ),
        CustomerCommissionSnapshot(
            customer_id="CUST-TAG-1", salesperson_id="1007", is_current=True, source="auto",
        ),
    ])
    db.commit()
    customer_path = "/api/customer-media/customers/CUST-TAG-1/tags"
    task_path = f"/api/customer-media/tasks/{batch.task_id}/customer-tags"
    with TestClient(_internal_app(db, _payload(applicant, "design:write"))) as client:
        response = client.post(customer_path, json={"tags": [
            {"dimension_id": dim.id, "tag_value_ids": [values[0].id]},
        ]})
        assert response.status_code == 200
        assert [tag["value"] for tag in client.get(customer_path).json()["data"]] == ["白底"]
        assert client.get("/api/customer-media/tags/dimensions").status_code == 200

    with TestClient(_internal_app(db, _payload(designer, "customer_media:write"))) as client:
        assert [tag["value"] for tag in client.get(task_path).json()["data"]] == ["白底"]
        response = client.post(task_path, json={"tags": [
            {"dimension_id": dim.id, "tag_value_ids": [values[1].id]},
        ]})
        assert response.status_code == 200

    with TestClient(_internal_app(db, _payload(applicant, "design:write"))) as client:
        assert {tag["value"] for tag in client.get(customer_path).json()["data"]} == {"白底", "场景"}
    with TestClient(_internal_app(db, _payload(outsider, "design:write"))) as client:
        assert client.get(customer_path).status_code == 403
    tag_service.invalidate_dim_cache()


def test_patch_tags_http_forbidden_and_review_list_carries_tags(db):
    customer_dim, values = _make_dim(db, "customer_general", "客户标签", values=["白底图"])
    applicant, designer, outsider, batch, asset = _seed_batch_with_asset(db)
    batch.status = "pending_review"
    batch.submitted_at = datetime(2026, 9, 2, 10, 0)
    db.commit()

    with TestClient(_internal_app(db, _payload(outsider, "customer_media:read"))) as client:
        forbidden = client.patch(
            f"/api/customer-media/batches/{batch.id}/assets/{asset.id}/tags",
            json={"tags": [{"dimension_id": customer_dim.id, "tag_value_ids": [values[0].id]}]},
        )
        assert forbidden.status_code == 403

    with TestClient(_internal_app(db, _payload(applicant, "customer_media:read"))) as client:
        patched = client.patch(
            f"/api/customer-media/batches/{batch.id}/assets/{asset.id}/tags",
            json={"tags": [{"dimension_id": customer_dim.id, "tag_value_ids": [values[0].id]}]},
        )
        assert patched.status_code == 200
        asset_payload = patched.json()["data"]["assets"][0]
        assert asset_payload["tags"] == [{
            "dimension_id": customer_dim.id, "dimension_label": "客户标签",
            "tag_value_id": values[0].id, "value": "白底图",
        }]
        reviews = client.get("/api/customer-media/reviews")
        assert reviews.status_code == 200
        review_asset = reviews.json()["data"][0]["assets"][0]
        assert review_asset["tags"][0]["value"] == "白底图"
        dimensions = client.get("/api/customer-media/tags/dimensions")
        assert {d["name"] for d in dimensions.json()["data"]} == {"customer_general"}
    tag_service.invalidate_dim_cache()


def test_sales_preview_tags_use_current_customer_scope_and_published_media(db):
    dim, values = _make_dim(db, "customer_scene", "场景", values=["白底", "户外"])
    applicant, designer, outsider, batch, asset = _seed_batch_with_asset(db)
    service.update_asset_tags(db, batch.id, asset.id, _payload(applicant, "customer_media:read"), [
        {"dimension_id": dim.id, "tag_value_ids": [values[0].id]},
    ])
    batch.status = "published"
    batch.published_at = datetime(2026, 9, 3, 10, 0)
    account = service.create_portal_account(
        db, _payload(applicant, "customer_media:admin"), "CUST-TAG-1",
        "client-tags@example.com", "ClientPass123",
    )
    db.add_all([
        ArkUserExternalBinding(
            ark_user_id=applicant.id, provider="okki", external_account_id="1007",
            binding_status="active", is_primary=True,
        ),
        ArkUserExternalBinding(
            ark_user_id=outsider.id, provider="okki", external_account_id="1008",
            binding_status="active", is_primary=True,
        ),
        CustomerCommissionSnapshot(
            customer_id="CUST-TAG-1", salesperson_id="1007", is_current=True, source="auto",
        ),
    ])
    db.commit()

    path = "/api/customer-media/sales-portal/customers/CUST-TAG-1/tags"
    with TestClient(_internal_app(db, _payload(applicant, "customer_media_portal:read"))) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["data"] == [{
            "dimension_id": dim.id, "label": "场景",
            "values": [{"id": values[0].id, "value": "白底", "count": 1}],
        }]
        account.is_active = False
        db.commit()
        assert client.get(path).json()["data"] == []

    with TestClient(_internal_app(db, _payload(outsider, "customer_media_portal:read"))) as client:
        assert client.get(path).status_code == 404


# ── 门户筛选与跨客户隔离 ─────────────────────────────────

def _publish(db, batch):
    batch.status = "published"
    batch.published_at = datetime(2026, 9, 3, 10, 0)
    db.commit()
    return batch


def _portal_app(db):
    app = FastAPI()
    app.include_router(public_router, prefix="/api/customer-media/portal")
    app.dependency_overrides[get_db] = lambda: db
    return app


def _login(client, email, password="ClientPass123"):
    response = client.post("/api/customer-media/portal/login", json={
        "email": email, "password": password,
    })
    assert response.status_code == 200


def test_portal_library_tag_filter_or_within_and_across_dimensions(db):
    dim_scene, scene = _make_dim(db, "customer_scene", "客户场景", values=["白底图", "场景图"])
    dim_series, series = _make_dim(db, "customer_series", "客户系列", values=["夏季"])
    applicant, designer, _outsider, batch, asset_a = _seed_batch_with_asset(db)
    asset_b = CustomerMediaAsset(
        batch_id=batch.id, file_name="scene.png", media_type="image",
        content_type="image/png", file_size=100, sha256="u" * 64,
        storage_provider="local", object_key="customers/tag-scene.png",
        uploaded_by=designer.id,
    )
    asset_c = CustomerMediaAsset(
        batch_id=batch.id, file_name="summer.png", media_type="image",
        content_type="image/png", file_size=100, sha256="v" * 64,
        storage_provider="local", object_key="customers/tag-summer.png",
        uploaded_by=designer.id,
    )
    db.add_all([asset_b, asset_c])
    db.flush()
    # A: 白底图；B: 场景图；C: 场景图+夏季
    db.add_all([
        CustomerMediaAssetTag(asset_id=asset_a.id, dimension_id=dim_scene.id, tag_value_id=scene[0].id),
        CustomerMediaAssetTag(asset_id=asset_b.id, dimension_id=dim_scene.id, tag_value_id=scene[1].id),
        CustomerMediaAssetTag(asset_id=asset_c.id, dimension_id=dim_scene.id, tag_value_id=scene[1].id),
        CustomerMediaAssetTag(asset_id=asset_c.id, dimension_id=dim_series.id, tag_value_id=series[0].id),
    ])
    _publish(db, batch)
    service.create_portal_account(
        db, _payload(applicant, "customer_media:admin"), "CUST-TAG-1",
        "client-tag@example.com", "ClientPass123",
    )

    batches = service.portal_library(db, db.query(service.CustomerPortalAccount).filter_by(
        customer_id="CUST-TAG-1").one())
    # 同维度 OR
    assert service.matching_asset_ids(db, batches, [scene[0].id, scene[1].id]) == {
        asset_a.id, asset_b.id, asset_c.id,
    }
    assert service.matching_asset_ids(db, batches, [scene[1].id]) == {asset_b.id, asset_c.id}
    # 跨维度 AND
    assert service.matching_asset_ids(db, batches, [scene[1].id, series[0].id]) == {asset_c.id}
    assert service.matching_asset_ids(db, batches, [scene[0].id, series[0].id]) == set()
    assert service.matching_asset_ids(db, batches, None) is None

    with TestClient(_portal_app(db)) as client:
        _login(client, "client-tag@example.com")
        full = client.get("/api/customer-media/portal/library")
        assert full.status_code == 200
        all_assets = full.json()["data"][0]["assets"]
        assert len(all_assets) == 3
        by_name = {a["file_name"]: a for a in all_assets}
        assert [t["value"] for t in by_name["summer.png"]["tags"]] == ["场景图", "夏季"]
        assert by_name["front.png"]["tags"][0]["value"] == "白底图"

        filtered = client.get(
            "/api/customer-media/portal/library",
            params={"tag_value_ids": f"{scene[1].id},{series[0].id}"},
        )
        assets = filtered.json()["data"][0]["assets"]
        assert [a["file_name"] for a in assets] == ["summer.png"]


def test_portal_tags_only_used_values_and_cross_customer_isolation(db):
    dim, values = _make_dim(db, "customer_scene", "客户场景", values=["白底图", "场景图", "未使用"])
    applicant, designer, _outsider, batch, asset = _seed_batch_with_asset(db)
    db.add(CustomerMediaAssetTag(asset_id=asset.id, dimension_id=dim.id, tag_value_id=values[0].id))
    _publish(db, batch)

    # 乙客户的已发布素材用了另一标签：只应出现在乙门户
    _add_customer(db, "CUST-TAG-2", "标签客户乙")
    other_request = DesignScheduleRequest(
        request_no="DR-TAG-002", customer_id="CUST-TAG-2", customer_name="标签客户乙",
        salesperson_id=applicant.id, salesperson_name=applicant.real_name,
        shoot_type="product", expect_start_date=date(2026, 9, 1),
        expect_end_date=date(2026, 9, 1), status="in_progress",
    )
    db.add(other_request)
    db.flush()
    designer_id = db.query(DesignDesigner).first().id
    other_task = DesignScheduleTask(
        request_id=other_request.id, task_no="DT-TAG-002", designer_id=designer_id,
        customer_id="CUST-TAG-2", customer_name="标签客户乙", status="in_progress",
    )
    db.add(other_task)
    db.flush()
    other_batch = CustomerMediaBatch(
        task_id=other_task.id, request_id=other_request.id, customer_id="CUST-TAG-2",
        customer_name_snapshot="标签客户乙", applicant_user_id=applicant.id,
        status="published", published_at=datetime(2026, 9, 3, 11, 0),
    )
    db.add(other_batch)
    db.flush()
    other_asset = CustomerMediaAsset(
        batch_id=other_batch.id, file_name="other.png", media_type="image",
        content_type="image/png", file_size=100, sha256="w" * 64,
        storage_provider="local", object_key="customers/tag-other.png",
        uploaded_by=applicant.id,
    )
    db.add(other_asset)
    db.flush()
    db.add(CustomerMediaAssetTag(asset_id=other_asset.id, dimension_id=dim.id, tag_value_id=values[1].id))
    db.commit()

    admin = _payload(applicant, "customer_media:admin")
    service.create_portal_account(db, admin, "CUST-TAG-1", "client-a-tag@example.com", "ClientPass123")
    service.create_portal_account(db, admin, "CUST-TAG-2", "client-b-tag@example.com", "ClientPass123")

    with TestClient(_portal_app(db)) as client:
        _login(client, "client-a-tag@example.com")
        tags_a = client.get("/api/customer-media/portal/tags")
        assert tags_a.status_code == 200
        data_a = tags_a.json()["data"]
        assert [d["dimension_id"] for d in data_a] == [dim.id]
        assert data_a[0]["label"] == "客户场景"
        # 只出本客户实际用到的值：场景图（乙客户用）与未使用都不出现
        assert data_a[0]["values"] == [{"id": values[0].id, "value": "白底图", "count": 1}]

    with TestClient(_portal_app(db)) as client:
        _login(client, "client-b-tag@example.com")
        tags_b = client.get("/api/customer-media/portal/tags")
        assert tags_b.json()["data"][0]["values"] == [
            {"id": values[1].id, "value": "场景图", "count": 1},
        ]
