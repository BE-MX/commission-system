"""Customer dedup: account normalisation, three-way verdict, auth, rate limit, audit."""

from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserExternalBinding, ArkUserRole
from app.auth.utils import create_access_token, generate_refresh_token
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer_dedup import service
from app.customer_dedup.models import CustomerDedupCheck
from app.customer_dedup.normalize import DedupInputError, build_lookup, key_for
from app.mcp.models import MCPToken


# ── normalisation ─────────────────────────────────────────

@pytest.mark.parametrize("stored", [
    "https://www.instagram.com/Hair.By_Amy/",
    "https://www.instagram.com/hair.by_amy/?hl=en",
    "http://instagram.com/hair.by_amy",
    "https://www.instagram.com/hair.by_amy?igsh=abc&utm_source=qr",
    "instagram.com/hair.by_amy",
    "@hair.by_amy",
    " hair.by_amy ",
    "https://www.instagram.com/stories/hair.by_amy/123/",
])
def test_instagram_variants_share_one_key(stored):
    assert key_for("instagram", stored) == "hair.by_amy"


def test_instagram_post_links_are_not_profiles():
    assert key_for("instagram", "https://www.instagram.com/p/AbC123/") == "post:AbC123"
    assert key_for("instagram", "https://www.instagram.com/reel/AbC123/") == "post:AbC123"


@pytest.mark.parametrize("stored,key", [
    ("https://www.facebook.com/GlamHair/", "glamhair"),
    ("http://facebook.com/glamhair?ref=page", "glamhair"),
    ("https://m.facebook.com/glamhair", "glamhair"),
    ("https://m.me/glamhair", "glamhair"),
    ("https://www.facebook.com/profile.php?id=100064123456789", "id:100064123456789"),
    ("https://www.facebook.com/people/Glam-Hair/100064123456789/", "id:100064123456789"),
    ("https://www.facebook.com/pages/Glam-Hair/100064123456789", "id:100064123456789"),
    ("https://www.facebook.com/p/Glam-Hair-100064123456789/", "id:100064123456789"),
    ("https://www.facebook.com/100064123456789", "id:100064123456789"),
    ("https://www.facebook.com/share/1AbCdE/?mibextid=xyz", "share:1AbCdE"),
])
def test_facebook_variants(stored, key):
    assert key_for("facebook", stored) == key


@pytest.mark.parametrize("stored", [
    "12025550123",
    "+1 (202) 555-0123",
    "+1 202-555-0123",
    "https://wa.me/12025550123",
    "https://wa.me/12025550123?text=hi",
    "https://api.whatsapp.com/send?phone=12025550123&text=hi",
    "https://api.whatsapp.com/send/?phone=%2B12025550123&type=phone_number&app_absent=0",
    "0012025550123",
])
def test_whatsapp_numbers_reduce_to_digits(stored):
    assert key_for("whatsapp", stored) == "tel:12025550123"


@pytest.mark.parametrize("family,stored,key", [
    ("tiktok", "https://www.tiktok.com/@Wig.Queen?_t=1&_r=1", "wig.queen"),
    ("tiktok", "https://www.tiktok.com/@wig.queen/video/7300000000", "wig.queen"),
    ("tiktok", "@wig.queen", "wig.queen"),
    ("x", "https://twitter.com/WigQueen?lang=en", "wigqueen"),
    ("x", "https://mobile.twitter.com/wigqueen/", "wigqueen"),
    ("x", "https://x.com/wigqueen", "wigqueen"),
    ("x", "https://hairshopx.com/collections/wigs", "url:hairshopx.com/collections/wigs"),
    ("linkedin", "https://nl.linkedin.com/in/Jane-Doe-123/?originalSubdomain=nl", "in:jane-doe-123"),
    ("linkedin", "http://linkedin.com/in/jane-doe-123", "in:jane-doe-123"),
    ("linkedin", "https://www.linkedin.com/company/glam-hair/about/", "company:glam-hair"),
    ("pinterest", "https://uk.pinterest.com/GlamHair/", "glamhair"),
    ("pinterest", "https://www.pinterest.com.au/glamhair/wigs/", "glamhair"),
    ("youtube", "https://www.youtube.com/@GlamHair", "@glamhair"),
    ("youtube", "https://www.youtube.com/channel/UCabcDEF?view_as=subscriber", "channel:UCabcDEF"),
    ("youtube", "http://www.youtube.com/user/GlamHair/videos", "user:glamhair"),
    ("yelp", "https://www.yelp.com/biz/glam-hair-houston?osq=Wigs", "biz:glam-hair-houston"),
    ("yelp", "https://m.yelp.com/biz/glam-hair-houston", "biz:glam-hair-houston"),
    ("wechat", " WigQueen88 ", "wigqueen88"),
    ("wechat", "+86 138 0013 8000", "tel:8613800138000"),
])
def test_other_platform_variants(family, stored, key):
    assert key_for(family, stored) == key


def test_platform_detected_from_link_and_aliases():
    assert build_lookup("https://www.instagram.com/foo_bar/").platform == "instagram"
    assert build_lookup("x.com/foo_bar").platform == "x"
    assert build_lookup("foo_bar", "Twitter").platform == "x"
    assert build_lookup("foo_bar", "ins").platform == "instagram"
    assert build_lookup("Sales@Example.COM").platform == "email"
    assert build_lookup("Sales@Example.COM").key == "sales@example.com"
    assert build_lookup("+1 202 555 0123").platform == "whatsapp"


@pytest.mark.parametrize("account,platform,fragment", [
    ("foo_bar", None, "platform"),
    ("https://example.com/foo", None, "无法从链接识别平台"),
    ("https://www.instagram.com/foo/", "tiktok", "不一致"),
    ("https://twitter.com/intent/tweet?text=x", None, "不是个人或公司主页"),
    ("foo", "myspace", "不支持的平台"),
    ("12345", "whatsapp", "位数太少"),
])
def test_unclassifiable_input_is_rejected_with_guidance(account, platform, fragment):
    with pytest.raises(DedupInputError) as exc:
        build_lookup(account, platform)
    assert fragment in str(exc.value)


# ── service / API fixtures ────────────────────────────────

@pytest.fixture
def mirror(db):
    db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN email TEXT"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.customer_contact_socials (
            id INTEGER PRIMARY KEY, customer_id TEXT, platform TEXT, value TEXT
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.user_basic (user_id, full_name, nickname) VALUES
        ('9001', '张三', NULL), ('9002', '', 'Lily'), ('9003', '我自己', NULL)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_info (company_id, company_name, owner_user_ids, email) VALUES
        ('C1', 'Glam Hair LLC', '[9001, 9002]', 'boss@glam.com,info@glam.com'),
        ('C2', 'Open Sea Wigs', '[]', NULL),
        ('C3', 'Mine Hair', '["9003"]', NULL)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts (id, company_id, customer_id, name, email) VALUES
        (1, 'C1', 'P1', 'Amy', 'amy@glam.com'),
        (2, 'C2', 'P2', 'Bob', 'bob@opensea.com'),
        (3, 'C3', 'P3', 'Cat', NULL)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) VALUES
        (1, 'P1', 'instagram', 'https://www.instagram.com/Glam.Hair_LA/?hl=en'),
        (2, 'P1', 'whatsapp', '+1 (202) 555-0123'),
        (3, 'P2', 'instagram', 'opensea_wigs'),
        (4, 'P2', 'twitter', 'https://twitter.com/OpenSeaWigs'),
        (5, 'P3', 'tiktok', 'https://www.tiktok.com/@minehair'),
        (6, 'P2', 'instagram', 'https://www.instagram.com/glamxhair_la/')
    """))
    db.flush()
    return db


def _user(db, uid=1, perms=("customer_dedup:read",)):
    user = ArkUser(id=uid, username=f"u{uid}", password_hash="x", real_name=f"u{uid}", is_active=True)
    db.add(user)
    role = ArkRole(id=uid, name=f"r{uid}", label=f"r{uid}")
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=uid, role_id=role.id))
    for code in perms:
        perm = db.query(ArkPermission).filter(ArkPermission.code == code).first()
        if perm is None:
            module, action = code.split(":")
            perm = ArkPermission(code=code, module=module, action=action, label=code)
            db.add(perm)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=perm.id))
    db.flush()
    return user


@contextmanager
def _client(db, bearer):
    from app.customer_dedup.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/customer-dedup")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, headers={"Authorization": f"Bearer {bearer}"}) as client:
        yield client


def _jwt(user, perms=("customer_dedup:read",), roles=()):
    return create_access_token({
        "sub": str(user.id), "username": user.username, "real_name": user.real_name,
        "roles": list(roles), "permissions": list(perms),
    })


def _personal_token(db, user):
    plain, token_hash = generate_refresh_token()
    db.add(MCPToken(token_hash=token_hash, user_id=user.id, label="dedup tool"))
    db.flush()
    return plain


# ── verdicts ──────────────────────────────────────────────

def test_private_customer_returns_company_and_colleague_names(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        body = client.post("/api/customer-dedup/check", json={"account": "@GLAM.HAIR_LA", "platform": "instagram"}).json()
    data = body["data"]
    assert body["code"] == 200
    assert data["status"] == "private"
    assert data["customers"] == [{
        "company_name": "Glam Hair LLC", "status": "private", "owners": ["张三", "Lily"], "is_mine": False,
    }]
    assert data["message"] == "该客户已进入同事私海：Glam Hair LLC（负责人：张三、Lily）"
    # LIKE '_' must not act as a wildcard: glamxhair_la is a different account.
    assert data["matched_count"] == 1


def test_public_customer(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "https://x.com/openseawigs"}).json()["data"]
    assert data["status"] == "public"
    assert data["message"] == "当前客户已进入公海，未绑定业务员：Open Sea Wigs"
    assert data["customers"][0]["owners"] == []


def test_not_found(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "nobody_here", "platform": "instagram"}).json()["data"]
    assert data == {
        "status": "not_found", "message": "当前系统尚未收录此客户", "platform": "instagram",
        "platform_label": "Instagram", "normalized_account": "nobody_here", "matched_count": 0, "customers": [],
    }


def test_whatsapp_number_in_any_format_matches(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        for account in ("12025550123", "https://wa.me/12025550123", "2025550123"):
            data = client.post("/api/customer-dedup/check", json={"account": account}).json()["data"]
            assert data["status"] == "private", account


def test_email_matches_contacts_and_comma_lists_case_insensitive(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "AMY@glam.com"}).json()["data"]["status"] == "private"
        assert client.post("/api/customer-dedup/check", json={"account": "info@glam.com"}).json()["data"]["status"] == "private"
        assert client.post("/api/customer-dedup/check", json={"account": "bob@opensea.com"}).json()["data"]["status"] == "public"
        assert client.post("/api/customer-dedup/check", json={"account": "fo@glam.com"}).json()["data"]["status"] == "not_found"


def test_own_customer_is_reported_as_mine(mirror):
    user = _user(mirror)
    mirror.add(ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki", external_account_id="9003",
        binding_status="active", is_primary=True,
    ))
    mirror.flush()
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "tiktok.com/@MineHair"}).json()["data"]
    assert data["customers"][0]["is_mine"] is True
    assert data["message"] == "该客户已在你自己的私海：Mine Hair"


def test_bad_input_is_400_with_reason(mirror):
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        resp = client.post("/api/customer-dedup/check", json={"account": "just_a_name"})
    assert resp.status_code == 400
    assert "platform" in resp.json()["detail"]


# ── auth, rate limit, audit ───────────────────────────────

def test_personal_token_works_and_is_audited(mirror):
    user = _user(mirror)
    token = _personal_token(mirror, user)
    with _client(mirror, token) as client:
        resp = client.post("/api/customer-dedup/check", json={"account": "@glam.hair_la", "platform": "ig"})
    assert resp.status_code == 200
    row = mirror.query(CustomerDedupCheck).one()
    assert (row.user_id, row.auth_channel, row.platform, row.normalized_value, row.result_status, row.matched_count) == (
        user.id, "personal_token", "instagram", "glam.hair_la", "private", 1,
    )


def test_personal_token_without_permission_is_403(mirror):
    user = _user(mirror, perms=())
    token = _personal_token(mirror, user)
    with _client(mirror, token) as client:
        resp = client.post("/api/customer-dedup/check", json={"account": "a@b.com"})
    assert resp.status_code == 403
    assert mirror.query(CustomerDedupCheck).count() == 0


def test_invalid_token_is_401(mirror):
    with _client(mirror, "not-a-real-token") as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 401


def test_super_admin_session_bypasses_permission(mirror):
    user = _user(mirror, perms=())
    mirror.query(ArkRole).filter(ArkRole.id == user.id).update({"name": "super_admin"})
    mirror.flush()
    with _client(mirror, _jwt(user, perms=())) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 200


def test_session_uses_live_permissions_not_jwt_snapshot(mirror):
    user = _user(mirror, perms=())
    # The JWT still claims the permission, but it was revoked in the database.
    with _client(mirror, _jwt(user, perms=("customer_dedup:read",))) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 403


def test_disabled_user_session_is_rejected(mirror):
    user = _user(mirror)
    user.is_active = False
    mirror.flush()
    with _client(mirror, _jwt(user)) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 401


def test_purpose_bound_jwt_is_rejected(mirror):
    user = _user(mirror)
    token = create_access_token({"sub": str(user.id), "run_id": "r1", "roles": [], "permissions": []})
    with _client(mirror, token) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 401


# Fixed Beijing clock 00:00:30: exercises the day boundary deterministically and keeps
# the window independent of the server's own timezone (red line 23).
_MIDNIGHT = datetime(2026, 11, 28, 0, 0, 30)


@pytest.fixture
def beijing_clock(monkeypatch):
    monkeypatch.setattr(service, "beijing_now", lambda: _MIDNIGHT)
    return _MIDNIGHT


def _history(db, user, count, at):
    for _ in range(count):
        db.add(CustomerDedupCheck(
            user_id=user.id, auth_channel="session", platform="email", normalized_value="x@y.com",
            result_status="not_found", matched_count=0, created_at=at,
        ))
    db.flush()


def test_rate_limit_per_minute_spans_midnight(mirror, beijing_clock):
    user = _user(mirror)
    _history(mirror, user, service.PER_MINUTE_LIMIT, beijing_clock - timedelta(seconds=40))  # 23:59:50 yesterday
    with _client(mirror, _jwt(user)) as client:
        resp = client.post("/api/customer-dedup/check", json={"account": "a@b.com"})
    assert resp.status_code == 429
    assert "每分钟" in resp.json()["detail"]


def test_daily_cap_resets_at_beijing_midnight(mirror, beijing_clock):
    user = _user(mirror)
    _history(mirror, user, service.PER_DAY_LIMIT, beijing_clock - timedelta(minutes=5))  # yesterday
    with _client(mirror, _jwt(user)) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 200
    row = mirror.query(CustomerDedupCheck).order_by(CustomerDedupCheck.id.desc()).first()
    assert row.created_at == beijing_clock and row.result_status == "not_found"


def test_daily_cap(mirror, monkeypatch):
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 28, 10, 0, 0))
    user = _user(mirror)
    _history(mirror, user, service.PER_DAY_LIMIT, datetime(2026, 11, 28, 0, 0, 0))  # first second of today
    with _client(mirror, _jwt(user)) as client:
        resp = client.post("/api/customer-dedup/check", json={"account": "a@b.com"})
    assert resp.status_code == 429
    assert "今天" in resp.json()["detail"]


def test_beijing_clock_ignores_server_timezone(monkeypatch):
    # A server running in UTC (or anywhere else) must still get Beijing wall-clock time.
    from datetime import timezone

    from app.core import time as ark_time

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 11, 27, 16, 0, 30, tzinfo=timezone.utc)  # = 00:00:30 Beijing
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(ark_time, "datetime", _FakeDateTime)
    assert ark_time.beijing_now() == _MIDNIGHT


def test_audit_row_is_reserved_before_lookup(mirror, monkeypatch):
    user = _user(mirror)
    seen = {}

    def spy(db, lookup):
        seen["pending"] = db.query(CustomerDedupCheck).filter_by(result_status="pending").count()
        return set()

    monkeypatch.setattr(service, "_email_company_ids", spy)
    with _client(mirror, _jwt(user)) as client:
        client.post("/api/customer-dedup/check", json={"account": "a@b.com"})
    assert seen["pending"] == 1
    assert mirror.query(CustomerDedupCheck).one().result_status == "not_found"


def test_percent_encoded_stored_link_is_found(mirror):
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) "
        "VALUES (7, 'P2', 'facebook', 'https://www.facebook.com/The%20Golden%20Hair')"
    ))
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "the golden hair", "platform": "fb"}).json()["data"]
    assert data["status"] == "public"


# ── review regressions ────────────────────────────────────

def test_candidate_cap_is_inconclusive_not_not_found(mirror, monkeypatch):
    monkeypatch.setattr(service, "MAX_CANDIDATES", 1)
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "glam.hair_la", "platform": "instagram"}).json()["data"]
    assert data["status"] == "inconclusive"
    assert mirror.query(CustomerDedupCheck).one().result_status == "inconclusive"


def test_contact_without_customer_record_is_inconclusive(mirror):
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contacts (id, company_id, customer_id, name) VALUES (9, 'C9', 'P9', 'Ghost')"
    ))
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) "
        "VALUES (9, 'P9', 'instagram', 'ghost_shop')"
    ))
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "@ghost_shop", "platform": "ig"}).json()["data"]
    assert data["status"] == "inconclusive"


def test_garbage_owner_ids_are_not_owners(mirror):
    mirror.execute(
        text("UPDATE lsordertest.customer_info SET owner_user_ids = :v WHERE company_id = 'C2'"),
        {"v": '[null, 0, true, ""]'},
    )
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        body = client.post("/api/customer-dedup/check", json={"account": "opensea_wigs", "platform": "ig"}).json()
    assert body["data"]["status"] == "public"


def test_semicolon_and_spaced_email_lists(mirror):
    mirror.execute(
        text("UPDATE lsordertest.customer_info SET email = :v WHERE company_id = 'C2'"),
        {"v": " Sales@OpenSea.com ; ops@opensea.com"},
    )
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        for account in ("sales@opensea.com", "mailto:ops@opensea.com"):
            assert client.post("/api/customer-dedup/check", json={"account": account}).json()["data"]["status"] == "public"


def test_bare_youtube_and_linkedin_handles_match_any_url_form(mirror):
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) VALUES "
        "(10, 'P2', 'youtube', 'https://www.youtube.com/@OpenSeaTV'), "
        "(11, 'P2', 'linkedin', 'https://www.linkedin.com/company/open-sea-wigs/')"
    ))
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        for account, platform in (("openseatv", "youtube"), ("open-sea-wigs", "linkedin")):
            data = client.post("/api/customer-dedup/check", json={"account": account, "platform": platform}).json()["data"]
            assert data["status"] == "public", platform


def test_co_owned_customer_names_the_colleague(mirror):
    user = _user(mirror)
    mirror.add(ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki", external_account_id="9001", binding_status="active", is_primary=True,
    ))
    mirror.flush()
    with _client(mirror, _jwt(user)) as client:
        data = client.post("/api/customer-dedup/check", json={"account": "glam.hair_la", "platform": "ig"}).json()["data"]
    assert data["message"] == "该客户已进入同事私海：Glam Hair LLC（负责人：张三、Lily）"
    assert data["customers"][0]["is_mine"] is True


@pytest.mark.parametrize("query,stored,intl,same", [
    ("12025550123", "12025550123", True, True),
    ("12025550123", "2025550123", True, True),       # stored without country code
    ("447911123456", "07911123456", True, True),     # stored with UK trunk 0
    ("12025550123", "4412025550123", True, False),   # two full international numbers
    ("7911123456", "447911123456", True, False),     # caller says intl, stored is longer
    ("2025550123", "12025550123", False, True),      # caller omitted country code
    ("07911123456", "447911123456", False, True),
    ("5550123", "12025550123", False, False),        # fragment too short
    ("202555012", "999912025550120", False, False),  # not a suffix
    ("123456789", "99999123456789", False, False),   # prefix longer than any country code
])
def test_phone_matching_rules(query, stored, intl, same):
    from app.customer_dedup.normalize import phones_match
    assert phones_match(query, stored, query_is_international=intl) is same


def test_international_flag_follows_input_form():
    assert build_lookup("+1 202 555 0123").phone_intl is True
    assert build_lookup("0012025550123").phone_intl is True
    assert build_lookup("https://wa.me/12025550123").phone_intl is True
    assert build_lookup("2025550123").phone_intl is False


def test_pair_grouped_numbers_are_found(mirror):
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) "
        "VALUES (12, 'P2', 'whatsapp', '+33 6 12 34 56 78')"
    ))
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        for account in ("+33612345678", "0612345678"):
            assert client.post("/api/customer-dedup/check", json={"account": account}).json()["data"]["status"] == "public", account


def test_full_international_number_does_not_match_other_country(mirror):
    mirror.execute(text(
        "INSERT INTO lsordertest.customer_contact_socials (id, customer_id, platform, value) "
        "VALUES (13, 'P1', 'whatsapp', '+44 1202 555 0123')"
    ))
    mirror.execute(text("DELETE FROM lsordertest.customer_contact_socials WHERE id = 2"))
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "+1 202 555 0123"}).json()["data"]["status"] == "not_found"


def test_mini_program_token_is_rejected(mirror):
    from app.mini.auth import create_mini_token

    user = _user(mirror)
    with _client(mirror, create_mini_token(user.id, "wx1")) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "a@b.com"}).status_code == 401


def test_email_list_cap_is_inconclusive(mirror, monkeypatch):
    monkeypatch.setattr(service, "_EMAIL_LIST_CAP", 1)
    mirror.execute(
        text("UPDATE lsordertest.customer_info SET email = :v WHERE company_id = 'C2'"),
        {"v": "x@opensea.com, sales@opensea.com"},
    )
    mirror.flush()
    user = _user(mirror)
    with _client(mirror, _jwt(user)) as client:
        assert client.post("/api/customer-dedup/check", json={"account": "sales@opensea.com"}).json()["data"]["status"] == "inconclusive"


def test_linkedin_path_without_host():
    assert build_lookup("in/Jane-Doe", "linkedin").match_keys == ("in:jane-doe",)
    assert build_lookup("company/glam-hair/", "linkedin").match_keys == ("company:glam-hair",)


def test_spoofed_hosts_are_not_social_platforms():
    for raw in ("https://pinterest.evil.com/foo", "https://yelp.evil.com/biz/foo"):
        with pytest.raises(DedupInputError):
            build_lookup(raw)
    assert build_lookup("https://www.pinterest.co.uk/foo/").platform == "pinterest"


def test_short_numeric_wechat_id_is_a_handle():
    assert build_lookup("123456", "wechat").key == "123456"
