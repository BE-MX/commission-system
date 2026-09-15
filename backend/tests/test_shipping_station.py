"""Shared phone identities, receipts and media against isolated SQLite only."""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from tests.test_shipping_inspection import _user, _pc_client, _mini_client, _qr, storage, product_display_source
from app.auth.models import ArkRole, ArkPermission
from app.shipping_inspection import station_service as station
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingStationSession, ShippingOperationEvent


@pytest.fixture
def people(db, monkeypatch):
    login, alice, bob = [_user(db, username=name) for name in ('phone', 'alice', 'bob')]
    role = ArkRole(name='fhqc', label='发货质检')
    alice.roles.append(role)
    bob.roles.append(role)
    device = ArkRole(name='shipping-device', label='质检共用手机')
    device.permissions.append(ArkPermission(code='shipping_station:write', module='shipping_station', action='write', label='共用手机'))
    login.roles.append(device)
    db.commit()
    # Python 3.12 SQLite legacy mode does not BEGIN for SELECT. Match MySQL's
    # real outer transaction before testing nested SAVEPOINT rollback.
    db.connection().connection.driver_connection.autocommit = False
    monkeypatch.setattr(station.get_settings(), 'SHIPPING_STATION_ROLE_ID', role.id)
    return login, alice, bob


def scan(client, operator, request_id=None, record='OB001'):
    return client.post('/api/shipping-inspection/station/scan', json={'qr_raw': _qr(record), 'operator_id': operator.id, 'request_id': request_id or str(uuid.uuid4())})


def photo(client, session, request_id='upload-one', **extra):
    return client.post(f'/api/shipping-inspection/station/sessions/{session}/photos', data={'edit_version': 0, 'request_id': request_id, **extra}, files={'file': ('test.jpg', b'jpeg', 'image/jpeg')})


def test_handoff_preserves_upload_author_and_submit_receipt(db, storage, people):
    login, alice, bob = people
    with _pc_client(db, login, []) as client:
        operators = client.get('/api/shipping-inspection/station/operators').json()['data']
        assert {x['id'] for x in operators} == {alice.id, bob.id}
        first = scan(client, alice, 'scan-one').json()['data']
        sid = first['session_id']
        assert scan(client, alice, 'scan-one').json()['data']['session_id'] == sid
        assert db.query(ShippingInspection).count() == 0
        assert client.get(f'/api/shipping-inspection/station/sessions/{sid}').status_code == 200
        assert db.query(ShippingOperationEvent).filter_by(action='scan').count() == 1
        uploaded = photo(client, sid).json()['data']
        assert photo(client, sid).json()['data']['id'] == uploaded['id']
        assert db.query(ShippingInspectionPhoto).count() == 1
        assert client.post(f'/api/shipping-inspection/station/sessions/{sid}/end').status_code == 200
        assert photo(client, sid, 'late-upload').status_code == 409
        second = scan(client, bob).json()['data']['session_id']
        body = {'edit_version': 0, 'request_id': 'submit-one', 'remark': '核对完成'}
        endpoint = f'/api/shipping-inspection/station/sessions/{second}/submit'
        receipt = client.post(endpoint, json=body)
        assert receipt.status_code == 200
        assert client.post(endpoint, json=body).json() == receipt.json()
    inspection = db.query(ShippingInspection).one()
    assert inspection.created_by == alice.id
    assert inspection.submitted_by == bob.id
    assert db.query(ShippingInspectionPhoto).one().created_by == alice.id
    event = db.query(ShippingOperationEvent).filter_by(action='submit').one()
    assert (event.operator_user_id, event.login_user_id) == (bob.id, login.id)


def test_invalid_operator_revocation_and_cross_record_media(db, storage, people):
    login, alice, bob = people
    with _pc_client(db, login, []) as client:
        assert scan(client, login).status_code == 403
        sid = scan(client, alice).json()['data']['session_id']
        media = photo(client, sid).json()['data']['id']
        other = scan(client, bob, record='OB002').json()['data']['session_id']
        assert client.get(f'/api/shipping-inspection/station/sessions/{other}/media/{media}').status_code == 404
        alice.is_active = False
        db.commit()
        assert photo(client, sid, 'revoked').status_code == 403
        assert db.query(ShippingInspectionPhoto).count() == 1


def test_expiry_and_wrong_login(db, storage, people):
    login, alice, bob = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
    with _pc_client(db, bob, ['shipping_station:write']) as client:
        assert client.get(f'/api/shipping-inspection/station/sessions/{sid}').status_code == 403
    session = db.get(ShippingStationSession, sid)
    session.last_active_at -= timedelta(minutes=16)
    db.commit()
    with _pc_client(db, login, []) as client:
        assert photo(client, sid).status_code == 409
        assert not list(storage.rglob('*.jpg'))


def test_authorized_other_login_role_removal_and_request_conflicts(db, storage, people):
    login, alice, bob = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice, 'same-scan').json()['data']['session_id']
        assert scan(client, bob, 'same-scan').status_code == 409
        assert photo(client, sid).status_code == 200
        assert photo(client, sid, item_id='IT001').status_code == 409
    bob.roles.append(db.query(ArkRole).filter_by(name='shipping-device').one())
    db.commit()
    with _pc_client(db, bob, []) as other:
        assert other.get(f'/api/shipping-inspection/station/sessions/{sid}').status_code == 404
    alice.roles = [r for r in alice.roles if r.name != 'fhqc']
    db.commit()
    with _pc_client(db, login, []) as client:
        assert photo(client, sid, 'after-role-removal').status_code == 403
    assert db.query(ShippingInspectionPhoto).count() == 1


def test_recall_version_and_submit_attribution(db, storage, people):
    login, alice, bob = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
        photo(client, sid)
        original = client.post(f'/api/shipping-inspection/station/sessions/{sid}/submit', json={'edit_version':0, 'request_id':'submit'}).json()
        inspection_id = original['data']['id']
        with _pc_client(db, alice, ['shipping_inspection:write']) as pc:
            assert pc.post(f'/api/shipping-inspection/records/{inspection_id}/recall', json={'edit_version':0}).status_code == 200
        # A lost old submit response can still be resolved; it cannot submit the new round.
        assert client.post(f'/api/shipping-inspection/station/sessions/{sid}/submit', json={'edit_version':0, 'request_id':'submit'}).json() == original
        assert db.get(ShippingInspection, inspection_id).status == 'draft'
        next_session = scan(client, bob).json()['data']['session_id']
        assert photo(client, next_session, 'old-version').status_code == 400
        assert photo(client, next_session, 'new-version', edit_version=1).status_code == 200
        result = client.post(f'/api/shipping-inspection/station/sessions/{next_session}/submit', json={'edit_version':1, 'request_id':'resubmit'})
        assert result.status_code == 200
    assert db.get(ShippingInspection, inspection_id).submitted_by == bob.id


def test_audit_failure_rolls_back_photo_and_draft(db, storage, people, monkeypatch):
    login, alice, _ = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
        def broken_audit(*args, **kwargs):
            raise RuntimeError('simulated audit outage')
        monkeypatch.setattr(station.audit_service, 'record', broken_audit)
        assert photo(client, sid).status_code == 500
    assert db.query(ShippingInspectionPhoto).count() == 0
    assert db.query(ShippingInspection).count() == 0
    assert not list(storage.rglob('*.jpg'))


def test_audit_beijing_midnight_ignores_server_timezone(db, people, monkeypatch):
    from app.core import time as clock
    class UTCServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 9, 15, 16, 0, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(clock, 'datetime', UTCServerClock)
    login, alice, _ = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
    assert db.get(ShippingStationSession, sid).created_at == datetime(2026, 9, 16, 0, 0, 1)
    assert db.query(ShippingOperationEvent).one().created_at == datetime(2026, 9, 16, 0, 0, 1)


def test_mini_scan_and_refresh_events_and_actor_are_preserved(db, people):
    _, alice, bob = people
    with _mini_client(db, alice) as client:
        body = {'qr_raw': _qr(), 'request_id': 'mini-scan-one', 'operator_id': bob.id}
        assert client.post('/api/mini/shipping-inspection/scan', json=body).status_code == 200
        assert client.post('/api/mini/shipping-inspection/scan', json=body).status_code == 200
        assert client.post('/api/mini/shipping-inspection/refresh', json=body).status_code == 200
    events = db.query(ShippingOperationEvent).all()
    assert len(events) == 1
    assert events[0].operator_user_id == events[0].login_user_id == alice.id


def test_permission_revoked_while_uploading_does_not_attach_file(db, storage, people, monkeypatch):
    login, alice, _ = people
    store = station.file_service.store_bytes
    def revoke_after_store(*args, **kwargs):
        path = store(*args, **kwargs)
        alice.roles = []
        db.commit()
        return path
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
        monkeypatch.setattr(station.file_service, 'store_bytes', revoke_after_store)
        assert photo(client, sid).status_code == 403
    assert db.query(ShippingInspectionPhoto).count() == 0
    assert not list(storage.rglob('*.jpg'))


def test_audit_login_identity_is_only_in_admin_projection(db, people):
    login, alice, _ = people
    with _pc_client(db, login, []) as client:
        assert scan(client, alice).status_code == 200
    public = station.audit_service.list_events(db, 'OB001')
    admin = station.audit_service.list_events(db, 'OB001', include_login=True)
    assert 'login_name' not in public[0]
    assert admin[0]['login_name'] == login.real_name
    assert public[0]['operator_name'] == alice.real_name


def test_station_video_attribution_preview_and_delete_without_photo_credit(db, storage, people):
    from tests.test_shipping_media_recall import VIDEO
    login, alice, _ = people
    with _pc_client(db, login, []) as client:
        sid = scan(client, alice).json()['data']['session_id']
        root = f'/api/shipping-inspection/station/sessions/{sid}'
        result = client.post(root+'/videos', data={'edit_version':0,'request_id':'video','item_id':'IT001'},
                             files={'file':('clip.mp4', VIDEO, 'video/mp4')})
        assert result.status_code == 200
        media_id = result.json()['data']['id']
        assert db.get(ShippingInspectionPhoto, media_id).created_by == alice.id
        assert client.get(root+f'/media/{media_id}').content == VIDEO
        assert client.post(root+'/submit', json={'edit_version':0,'request_id':'video-only-submit'}).status_code == 400
        assert db.query(ShippingInspection).one().photo_count == 0
        query = {'edit_version':0,'request_id':'delete-video'}
        assert client.delete(root+f'/media/{media_id}', params=query).status_code == 200
        assert client.delete(root+f'/media/{media_id}', params=query).status_code == 200
        assert db.query(ShippingInspectionPhoto).count() == 0
