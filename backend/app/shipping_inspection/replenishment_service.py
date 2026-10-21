"""One current-authorized immediate stock recheck under the shared executor fence."""
import json
import re

from sqlalchemy import select
from app.invoice import outbound_mode, outbound_worker as worker
from app.invoice.models import OkkiOutboundTask
from app.shipping_inspection import outbound_inventory_service as inventory
from app.shipping_inspection.outbound_prepare import current, reject


def authorize(db, record_id, user):
    actor = current(db, user, warehouse=True)
    from app.shipping_inspection.router import _outbound_scope
    record, _, _, _ = inventory._source(db, record_id, _outbound_scope(db, actor))
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.id == int(record_id[5:]))
                     .with_for_update().execution_options(populate_existing=True))
    if task is None or str(task.order_id) != record['order_id']:
        reject(404, '待出库任务不存在')
    return actor, task


def synchronize(db, record_id, user):
    if not re.fullmatch(r'task:[1-9][0-9]*', record_id):
        reject(409, '补货同步仅适用于尚未生成的缺货出库任务')
    try:
        actor, task = authorize(db, record_id, user)
        invoice_id, task_id, actor_id = task.invoice_id, task.id, actor['id']
        db.commit();worker.clear(db)
        with outbound_mode.executor_fence(db) as acquired:
            if not acquired:
                return {'status':'busy', 'message':'出库执行正在处理其他任务，请稍后重试'}
            mode = outbound_mode.read_mode(db)
            if mode not in (outbound_mode.LEGACY, outbound_mode.MODE):
                reject(409, '当前出库执行模式待核对')
            worker.clear(db)
            actor, task = authorize(db, record_id, user)
            if (task.id, task.invoice_id, actor['id']) != (task_id, invoice_id, actor_id):
                reject(409, '补货同步目标或权限已变化')
            original = worker.facts.unresolved(db, invoice_id)
            if original:
                if len(original) != 1 or original[0].data.get('manual_actor') != actor_id:
                    reject(409, '原出库提交结果待核对，禁止新建或重发')
            elif task.status == 'done':
                return {'status':'done', 'message':'该出库任务已完成，请刷新查看'}
            elif task.status != 'waiting_stock':
                reject(409, '任务已变化，仅库存不足的任务可以补货同步')
            db.commit();worker.clear(db)
            db.info['outbound_manual_actor'] = actor_id
            result = worker.process(db, invoice_id, immediate=True)
            actor, task = authorize(db, record_id, user)
            shortages = []
            if task.status == 'waiting_stock':
                data = json.loads(task.last_error or '{}')
                shortages = data.get('shortages', []) if isinstance(data, dict) else []
            result.update(shortages=shortages, message={
                'done':'补货同步完成，小满出库单已生成并核验；列表镜像可能稍后到达',
                'waiting_stock':'已同步目标仓库实时库存，仍有明细库存不足',
                'processing':'原补货同步正在处理，请稍后刷新核对',
                'uncertain':'出库提交结果待核对，请勿重复发送',
                'skipped':'已发现关联出库单，请核对原单，未重复生成',
            }.get(result['status'], '任务状态已更新，请刷新核对'))
            db.commit();worker.clear(db)
            return result
    finally:
        db.info.pop('outbound_manual_actor', None)
        worker.clear(db)
