"""钉钉事件回调：签名校验、解密、加密应答与拒绝路径"""

import base64
import hashlib
import json
import struct
import time

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.dingtalk.callback import router as callback_router
from app.dingtalk.callback_crypto import (
    MAX_TIMESTAMP_SKEW_MS,
    CallbackCryptoError,
    DingTalkCallbackCrypto,
)
from app.dingtalk.models import DingTalkCallbackLog

TOKEN = "test-callback-token"
AES_KEY = base64.b64encode(bytes(range(32))).decode().rstrip("=")
APP_KEY = "dingtestappkey000001"


def _push(crypto: DingTalkCallbackCrypto, event: dict, *, timestamp: str | None = None):
    """模拟钉钉推送：加密事件，返回 (query, body)"""
    packed = crypto.encrypt(json.dumps(event), timestamp=timestamp)
    query = {"signature": packed["msg_signature"], "timestamp": packed["timeStamp"], "nonce": packed["nonce"]}
    return query, {"encrypt": packed["encrypt"]}


@pytest.fixture
def configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "DINGTALK_CALLBACK_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "DINGTALK_CALLBACK_AES_KEY", AES_KEY)
    monkeypatch.setattr(settings, "DINGTALK_CALLBACK_RECEIVER_ID", APP_KEY)
    return DingTalkCallbackCrypto(TOKEN, AES_KEY, APP_KEY)


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(callback_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _reply_plaintext(reply: dict) -> str:
    # 应答明文是 "success" 而非 JSON，独立于被测代码按协议手工拆包验证
    expected = hashlib.sha1("".join(sorted([TOKEN, reply["timeStamp"], reply["nonce"], reply["encrypt"]])).encode()).hexdigest()
    assert reply["msg_signature"] == expected
    key = base64.b64decode(AES_KEY + "=")
    dec = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    plain = dec.update(base64.b64decode(reply["encrypt"])) + dec.finalize()
    plain = plain[: -plain[-1]]
    (n,) = struct.unpack(">I", plain[16:20])
    assert plain[20 + n :].decode() == APP_KEY
    return plain[20 : 20 + n].decode()


def test_check_url_gets_encrypted_success_without_logging(api, db, configured):
    query, body = _push(configured, {"EventType": "check_url"})
    resp = api.post("/api/dingtalk/callback", params=query, json=body)
    assert resp.status_code == 200
    assert _reply_plaintext(resp.json()) == "success"
    assert db.query(DingTalkCallbackLog).count() == 0


def test_signed_approval_event_is_logged_and_processed(api, db, configured):
    event = {"EventType": "bpms_instance_change", "processInstanceId": "pi-1", "type": "finish", "result": "agree"}
    query, body = _push(configured, event)
    resp = api.post("/api/dingtalk/callback", params=query, json=body)
    assert resp.status_code == 200
    assert _reply_plaintext(resp.json()) == "success"
    log = db.query(DingTalkCallbackLog).one()
    assert log.event_type == "bpms_instance_change"
    assert json.loads(log.raw_data)["processInstanceId"] == "pi-1"
    assert log.processed is True


def test_legacy_msg_signature_param_is_accepted(api, configured):
    query, body = _push(configured, {"EventType": "check_url"})
    query["msg_signature"] = query.pop("signature")
    assert api.post("/api/dingtalk/callback", params=query, json=body).status_code == 200


def test_plaintext_event_is_rejected_and_not_logged(api, db, configured):
    resp = api.post("/api/dingtalk/callback", json={"EventType": "bpms_instance_change", "processInstanceId": "forged"})
    assert resp.status_code == 400
    assert db.query(DingTalkCallbackLog).count() == 0


def test_tampered_signature_is_rejected(api, db, configured):
    query, body = _push(configured, {"EventType": "bpms_task_change"})
    query["signature"] = "0" * 40
    resp = api.post("/api/dingtalk/callback", params=query, json=body)
    assert resp.status_code == 403
    assert resp.text == "bad_signature"
    assert db.query(DingTalkCallbackLog).count() == 0


def test_wrong_token_cannot_forge(api, db, configured):
    forger = DingTalkCallbackCrypto("guessed-token", AES_KEY, APP_KEY)
    query, body = _push(forger, {"EventType": "bpms_task_change"})
    assert api.post("/api/dingtalk/callback", params=query, json=body).status_code == 403
    assert db.query(DingTalkCallbackLog).count() == 0


def test_other_app_payload_is_rejected(api, configured):
    other = DingTalkCallbackCrypto(TOKEN, AES_KEY, "dingotherapp00000001")
    query, body = _push(other, {"EventType": "check_url"})
    resp = api.post("/api/dingtalk/callback", params=query, json=body)
    assert resp.status_code == 403
    assert resp.text == "receiver_mismatch"


def test_replay_outside_window_is_rejected(api, configured):
    old = str(int(time.time() * 1000) - MAX_TIMESTAMP_SKEW_MS - 60_000)
    query, body = _push(configured, {"EventType": "check_url"}, timestamp=old)
    resp = api.post("/api/dingtalk/callback", params=query, json=body)
    assert resp.status_code == 403
    assert resp.text == "stale_timestamp"


def test_unconfigured_callback_rejects_everything(api, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DINGTALK_CALLBACK_TOKEN", "")
    resp = api.post("/api/dingtalk/callback", json={"EventType": "bpms_instance_change"})
    assert resp.status_code == 503
    assert db.query(DingTalkCallbackLog).count() == 0


def test_non_ascii_signature_is_rejected_not_500(api, configured):
    query, body = _push(configured, {"EventType": "check_url"})
    query["signature"] = "é"
    assert api.post("/api/dingtalk/callback", params=query, json=body).status_code == 403


def test_deeply_nested_json_is_rejected_not_500(api, configured):
    resp = api.post("/api/dingtalk/callback", content=b"[" * 100_000, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


def test_oversized_body_is_rejected(api, configured):
    resp = api.post("/api/dingtalk/callback", content=b" " * (300 * 1024), headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


def test_missing_receiver_id_rejects_everything(api, monkeypatch, configured):
    monkeypatch.setattr(get_settings(), "DINGTALK_CALLBACK_RECEIVER_ID", "")
    query, body = _push(configured, {"EventType": "check_url"})
    assert api.post("/api/dingtalk/callback", params=query, json=body).status_code == 503


def test_invalid_json_is_rejected(api, configured):
    resp = api.post("/api/dingtalk/callback", content=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


@pytest.mark.parametrize("aes_key", ["", "short", AES_KEY + "x"])
def test_invalid_aes_key_is_a_configuration_error(aes_key):
    with pytest.raises(CallbackCryptoError):
        DingTalkCallbackCrypto(TOKEN, aes_key, APP_KEY)


def test_corrupted_ciphertext_with_valid_signature_is_rejected(configured):
    ts, nonce, encrypt = str(int(time.time() * 1000)), "n1", base64.b64encode(b"x" * 32).decode()
    sig = hashlib.sha1("".join(sorted([TOKEN, ts, nonce, encrypt])).encode()).hexdigest()
    with pytest.raises(CallbackCryptoError):
        configured.decrypt(sig, ts, nonce, encrypt)


def test_official_dingtalk_vector_decrypts():
    # open-dingtalk/DingTalk-Callback-Crypto DingCallbackCrypto3.py 中的真实 check_url 推送样例
    crypto = DingTalkCallbackCrypto("mryue", "Yue0EfdN5900c1ce5cf6A152c63DDe1808a60c5ecd7", "ding6ccabc44d2c8d38b")
    event = crypto.decrypt(
        "03044561471240d4a14bb09372dfcfd4fd0e40cb",
        "1608001896814",
        "WL4PK6yA",
        "0vJiX6vliEpwG3U45CtXqi+m8PXbQRARJ8p8BbDuD1EMTDf0jKpQ79QS93qEk7XHpP6u+oTTrd15NRPvNvmBKyDCYxxOK+HZeKju4yhELOFchzNukR+t8SB/qk4ROMu3",
        now_ms=1608001896814,
    )
    assert event == {"EventType": "check_url"}
