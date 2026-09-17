"""Application robot transport. No public URLs for private knowledge images.

Protocol references: https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message
https://open.dingtalk.com/document/orgapp/upload-media-files
"""
import asyncio
import json
import httpx

from app.dingtalk.client import DingTalkClient
from app.knowledge.image_service import resolve_private_path
from app.knowledge.models import KnowledgeAsset


class AnnouncementSendError(Exception):
    def __init__(self, code, *, uncertain=False, retryable=False):
        self.code, self.uncertain, self.retryable = code, uncertain, retryable
        super().__init__(code)


async def prepare(db, payload):
    """Media upload can safely retry; message submission happens separately."""
    client = DingTalkClient()
    if not client.app_key or not client.app_secret:
        raise AnnouncementSendError('应用机器人凭据未配置')
    token = await client.get_access_token()
    if payload['kind'] == 'image':
        asset = db.get(KnowledgeAsset, payload['asset_id'])
        if not asset or asset.deleted_at:
            raise AnnouncementSendError('公告图片不存在')
        path = resolve_private_path(asset.storage_path)
        if not path.is_file():
            raise AnnouncementSendError('公告图片文件缺失')
        async with httpx.AsyncClient(timeout=30) as http:
            with path.open('rb') as source:
                response = await http.post('https://oapi.dingtalk.com/media/upload', params={'access_token': token, 'type': 'image'},
                                           files={'media': (path.name, source, asset.mime_type)})
            if response.status_code != 200:
                raise AnnouncementSendError('图片上传失败', retryable=True)
            result = response.json()
        if result.get('errcode') != 0 or not result.get('media_id'):
            raise AnnouncementSendError('图片上传被拒绝')
        return token, 'sampleImageMsg', {'photoURL': result['media_id']}
    prefix = f"（{payload['sequence']}/{payload['total']}）\n" if payload.get('total', 1) > 1 else ''
    return token, 'sampleMarkdown', {'title': payload.get('title', '公告')[:100], 'text': prefix + payload['text']}


async def send_prepared(token, target, robot_code, key, params):
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post('https://api.dingtalk.com/v1.0/robot/groupMessages/send',
                headers={'x-acs-dingtalk-access-token': token}, json={'robotCode': robot_code,
                    'openConversationId': target, 'msgKey': key, 'msgParam': json.dumps(params, ensure_ascii=False)})
        if response.status_code == 429:
            raise AnnouncementSendError('钉钉限流', retryable=True)
        if response.status_code >= 500:
            raise AnnouncementSendError('钉钉服务错误，投递结果不确定', uncertain=True)
        if response.status_code != 200:
            raise AnnouncementSendError(f'钉钉拒绝消息（HTTP {response.status_code}）')
        result = response.json()
        receipt = result.get('processQueryKey')
        if not receipt:
            raise AnnouncementSendError('钉钉未返回投递回执', uncertain=True)
        return str(receipt)[:256]
    except (httpx.TimeoutException, httpx.TransportError, ValueError) as exc:
        raise AnnouncementSendError('网络或响应异常，投递结果不确定', uncertain=True) from exc


def prepare_message(db, payload):
    return asyncio.run(prepare(db, payload))


def send_message(prepared, target, robot_code):
    token, key, params = prepared
    return asyncio.run(send_prepared(token, target, robot_code, key, params))
