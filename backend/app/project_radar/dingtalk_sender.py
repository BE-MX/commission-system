"""方舟雷达钉钉单聊发送与可靠发件箱。"""

from __future__ import annotations

from datetime import timedelta
import json
import logging
from urllib.parse import urlencode

import httpx
from sqlalchemy import update as sa_update

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.project_radar.deep_link import issue_detail_token
from app.project_radar.digest import complete_digest_delivery
from app.project_radar.models import RadarDigest, RadarOutbox

logger = logging.getLogger("commission.project_radar.dingtalk")


class RadarDingTalkError(RuntimeError):
    pass


def detail_url(settings, user_id: int, subscription_id: int) -> str:
    secret = settings.PROJECT_RADAR_DETAIL_SECRET or settings.JWT_SECRET_KEY
    token = issue_detail_token(secret, user_id, subscription_id)
    query = urlencode({"user_id": user_id, "token": token})
    base = settings.PROJECT_RADAR_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/insight/project-radar/shared/{subscription_id}?{query}"


class RadarDingTalkSender:
    def __init__(self):
        self.settings = get_settings()

    def _token(self, client: httpx.Client) -> str:
        if not self.settings.PROJECT_RADAR_DINGTALK_APP_KEY or not self.settings.PROJECT_RADAR_DINGTALK_APP_SECRET:
            raise RadarDingTalkError("方舟雷达机器人凭据未配置")
        response = client.get("https://oapi.dingtalk.com/gettoken", params={
            "appkey": self.settings.PROJECT_RADAR_DINGTALK_APP_KEY,
            "appsecret": self.settings.PROJECT_RADAR_DINGTALK_APP_SECRET,
        }, timeout=10)
        payload = response.json()
        if payload.get("errcode") != 0 or not payload.get("access_token"):
            raise RadarDingTalkError("方舟雷达机器人鉴权失败")
        return payload["access_token"]

    def send(self, user: ArkUser, *, title: str, text: str, action_url: str | None = None) -> str:
        if not user.dingtalk_id:
            raise RadarDingTalkError("用户尚未同步钉钉 ID")
        if not self.settings.PROJECT_RADAR_DINGTALK_ROBOT_CODE:
            raise RadarDingTalkError("方舟雷达 robotCode 未配置")
        try:
            with httpx.Client(timeout=15) as client:
                token = self._token(client)
                msg_key = "sampleActionCard" if action_url else "sampleMarkdown"
                params = {"title": title[:100], "text": text}
                if action_url:
                    params.update({"singleTitle": "打开详情", "singleURL": action_url})
                response = client.post(
                    "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
                    headers={"x-acs-dingtalk-access-token": token},
                    json={"robotCode": self.settings.PROJECT_RADAR_DINGTALK_ROBOT_CODE,
                          "userIds": [user.dingtalk_id], "msgKey": msg_key,
                          "msgParam": json.dumps(params, ensure_ascii=False)},
                    timeout=15,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise RadarDingTalkError("钉钉暂时不可用，投递结果待核对")
                if response.status_code != 200:
                    raise RadarDingTalkError(f"钉钉拒绝消息（HTTP {response.status_code}）")
                payload = response.json()
                receipt = payload.get("processQueryKey")
                if not receipt:
                    raise RadarDingTalkError("钉钉未返回投递回执，结果待核对")
                return str(receipt)[:256]
        except RadarDingTalkError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise RadarDingTalkError("钉钉网络或响应异常，投递结果待核对") from exc


def enqueue_message(db, user_id: int, dedup_key: str, payload: dict, *, kind="markdown"):
    existing = db.query(RadarOutbox).filter(RadarOutbox.dedup_key == dedup_key).one_or_none()
    if existing:
        return existing
    row = RadarOutbox(user_id=user_id, dedup_key=dedup_key, kind=kind, payload=payload, created_at=beijing_now())
    db.add(row)
    db.flush()
    return row


def deliver_pending_outbox(db, *, sender=None, limit=50):
    sender = sender or RadarDingTalkSender()
    stale_rows = db.query(RadarOutbox).filter(
        RadarOutbox.status == "sending",
        RadarOutbox.claimed_at < beijing_now() - timedelta(minutes=15),
    ).all()
    for stale in stale_rows:
        stale.status = "failed"
        stale.last_error = "投递中断，结果待人工核对；为避免重复消息不自动重发"
        if stale.kind == "digest":
            digest = db.get(RadarDigest, stale.payload["digest_id"])
            if digest:
                digest.status = "failed"
    db.commit()
    rows = db.query(RadarOutbox).filter(RadarOutbox.status == "pending").order_by(RadarOutbox.created_at).limit(limit).all()
    sent = 0
    failed = len(stale_rows)
    for outbox in rows:
        claimed = db.execute(sa_update(RadarOutbox).where(
            RadarOutbox.id == outbox.id, RadarOutbox.status == "pending",
        ).values(
            status="sending", claimed_at=beijing_now(), attempts=RadarOutbox.attempts + 1,
        )).rowcount
        if claimed != 1:
            continue
        db.commit()
        db.refresh(outbox)
        try:
            user = db.get(ArkUser, outbox.user_id)
            if user is None or not user.is_active or user.deleted_at:
                raise RadarDingTalkError("用户不可用")
            payload = dict(outbox.payload or {})
            action_url = None
            if outbox.kind == "digest":
                digest = db.get(RadarDigest, payload["digest_id"])
                title = digest.content.splitlines()[0]
                base = sender.settings.PROJECT_RADAR_PUBLIC_BASE_URL.rstrip("/")
                text = f"{digest.content}\n\n[打开项目雷达]({base}/insight/project-radar)"
            else:
                title = payload.get("title") or "方舟雷达"
                text = payload.get("text") or ""
                subscription_id = payload.get("subscription_id")
                if subscription_id:
                    action_url = detail_url(sender.settings, outbox.user_id, subscription_id)
            receipt = sender.send(user, title=title, text=text, action_url=action_url)
            outbox.payload = {**payload, "dingtalk_ref": receipt}
            if outbox.kind == "digest":
                complete_digest_delivery(db, outbox)
            outbox.status = "sent"
            outbox.sent_at = beijing_now()
            outbox.last_error = None
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project radar outbox failed id=%s (%s)", outbox.id, type(exc).__name__)
            print(f"Project radar outbox failed id={outbox.id} ({type(exc).__name__})", flush=True)
            outbox.status = "failed"
            outbox.last_error = str(exc)[:500]
            if outbox.kind == "digest":
                digest = db.get(RadarDigest, outbox.payload["digest_id"])
                if digest:
                    digest.status = "failed"
            failed += 1
        db.commit()
    if failed:
        raise RuntimeError(f"项目雷达有 {failed} 条钉钉消息投递失败")
    return sent
