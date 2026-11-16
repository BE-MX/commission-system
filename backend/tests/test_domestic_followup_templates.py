from tests.domestic_followup_helpers import followup_client, grant, make_user

READ = ("domestic_followup:read",)
ADMIN = ("domestic_followup:read", "domestic_followup:write", "domestic_followup:admin")


def _seed_templates(db):
    from app.domestic_followup.template_models import DomesticFollowupTemplate

    db.add(DomesticFollowupTemplate(
        code="T03", version=1, name="价格异议", status="active", prep_fields=[], record_fields=[],
        guidance="先核实比较口径", short_form="价格含义待确认", params={}, avoid=[],
    ))
    db.flush()


def test_template_admin_requires_permission(db):
    user = make_user(db, "tpl_reader")
    _seed_templates(db)
    with followup_client(db, user, permissions=READ) as client:
        assert client.get("/api/domestic-followup/templates").status_code == 200
        response = client.put("/api/domestic-followup/admin/templates/T03", json={
            "version": 1, "name": "价格异议", "prep_fields": [], "record_fields": [],
        })
        assert response.status_code == 403


def test_template_save_creates_version_and_rejects_stale_write(db):
    user = make_user(db, "tpl_admin")
    grant(db, user, *ADMIN)
    _seed_templates(db)
    payload = {
        "version": 1, "name": "价格异议 / 报价后犹豫", "short_form": "金额含义待确认",
        "guidance": "先分清采购价、终端售价和比较价格",
        "prep_fields": [{"key": "product", "label": "涉及产品", "kind": "text", "emphasis": "key"}],
        "record_fields": [{"key": "amount_meaning", "label": "金额及含义", "kind": "amount",
                           "nature": "to_confirm", "options": {"inline": ["未确认"]}}],
        "params": {"prep_minutes": [3, 5]}, "avoid": [],
    }
    with followup_client(db, user, permissions=ADMIN) as client:
        saved = client.put("/api/domestic-followup/admin/templates/T03", json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["version"] == 2
        stale = client.put("/api/domestic-followup/admin/templates/T03", json=payload)
        assert stale.status_code == 409
        current = client.get("/api/domestic-followup/templates/T03")
        historical = client.get("/api/domestic-followup/templates/T03", params={"version": 1})
        versions = client.get("/api/domestic-followup/admin/templates/T03/versions")
        assert current.json()["data"]["status"] == "active"
        assert current.json()["data"]["version"] == 2
        assert historical.json()["data"]["version"] == 1
        assert historical.json()["data"]["status"] == "retired"
        assert [row["version"] for row in versions.json()["data"]] == [2, 1]


def test_template_rejects_invalid_field_definitions(db):
    user = make_user(db, "tpl_invalid")
    grant(db, user, *ADMIN)
    _seed_templates(db)
    with followup_client(db, user, permissions=ADMIN) as client:
        response = client.put("/api/domestic-followup/admin/templates/T03", json={
            "version": 1, "name": "价格异议", "prep_fields": [],
            "record_fields": [{"key": "amount", "label": "金额", "kind": "unknown"}],
        })
        assert response.status_code == 400
        duplicate = client.put("/api/domestic-followup/admin/templates/T03", json={
            "version": 1, "name": "价格异议", "prep_fields": [],
            "record_fields": [
                {"key": "same", "label": "甲", "kind": "text"},
                {"key": "same", "label": "乙", "kind": "text"},
            ],
        })
        assert duplicate.status_code == 400
