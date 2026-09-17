"""Explicit operator-initiated image/text test; never runs at initialization."""
from io import BytesIO
from uuid import uuid4
from PIL import Image, ImageDraw

from app.knowledge import asset_service, service as knowledge
from app.knowledge.managed import announcement_scope
from app.announcement import service
from app.announcement.models import Delivery


def request_test(db, identity):
    config = service.config_for(db, identity, 'admin', True)
    if not config.conversation_id or not config.robot_code:
        raise knowledge.ValidationError('请先保存机器人和目标群')
    picture = Image.new('RGB', (480, 160), 'white')
    ImageDraw.Draw(picture).text((30, 65), 'ARK ANNOUNCEMENT IMAGE TEST', fill='black')
    data = BytesIO()
    picture.save(data, format='PNG')
    with announcement_scope(config.library_id):
        asset = asset_service.create_image_asset(db, identity, config.library_id,
            original_name='announcement-test.png', mime_type='image/png', content=data.getvalue())
    key = f'test:{uuid4().hex}'
    parts = [{'kind': 'text', 'text': '方舟公告图文通道测试：下一条应显示 ARK ANNOUNCEMENT IMAGE TEST 图片。', 'title': '公告通道测试'},
             {'kind': 'image', 'asset_id': asset.id, 'title': '公告通道测试'}]
    for i, part in enumerate(parts, 1):
        db.add(Delivery(source_key=key, sequence=i, target=config.conversation_id, robot_code=config.robot_code,
                        config_version=config.version, payload={**part, 'sequence': i, 'total': 2, 'acl': service.acl_fingerprint(db, config.library_id)}))
    db.commit()
    return {'test_key': key}


def verify(db, identity, test_key):
    config = service.config_for(db, identity, 'admin', True)
    tasks = db.query(Delivery).filter_by(source_key=test_key).all()
    if not test_key.startswith('test:') or len(tasks) != 2 or any(t.status != 'sent' or t.target != config.conversation_id or t.robot_code != config.robot_code for t in tasks):
        raise knowledge.ConflictError('请等待当前群的两条测试消息发送成功，并核对图片可见')
    config.channel_verified = True
    knowledge._audit(db, identity, config.library_id, 'announcement_channel_verified', 'library', config.library_id)
    db.commit()
