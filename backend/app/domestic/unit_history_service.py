"""Read-only per-piece process history, including revoked and skipped records."""
from app.domestic.models import (DomesticItemUnit, DomesticOrderItem, DomesticOrder,
    DomesticItemProgress, DomesticReportLog, DomesticReportUnit, DomesticSkipLog, DomesticSkipUnit)
from app.domestic.unit_service import unit_display_code
from app.production.models import Process
from app.auth.models import ArkUser


def get_unit_history(db, unit_id):
    unit = db.get(DomesticItemUnit, unit_id)
    item = db.get(DomesticOrderItem, unit.item_id) if unit else None
    order = db.get(DomesticOrder, item.order_id) if item else None
    if not unit or not item or not order:
        raise ValueError('找不到这个逐件码对应的记录')
    steps = db.query(DomesticItemProgress, Process.name).join(
        Process, Process.id == DomesticItemProgress.process_id,
    ).filter(DomesticItemProgress.item_id == item.id).order_by(DomesticItemProgress.step_order).all()
    reports = db.query(DomesticReportLog).join(DomesticReportUnit,
        DomesticReportUnit.log_id == DomesticReportLog.id).filter(
        DomesticReportUnit.unit_id == unit.id, DomesticReportLog.item_id == item.id,
    ).order_by(DomesticReportLog.reported_at, DomesticReportLog.id).all()
    skips = db.query(DomesticSkipLog, ArkUser.real_name).join(DomesticSkipUnit,
        DomesticSkipUnit.skip_log_id == DomesticSkipLog.id).outerjoin(ArkUser,
        ArkUser.id == DomesticSkipLog.created_by_user_id).filter(
        DomesticSkipUnit.unit_id == unit.id, DomesticSkipLog.item_id == item.id,
    ).order_by(DomesticSkipLog.created_at, DomesticSkipLog.id).all()
    records = {}
    for log in reports:
        records.setdefault(log.progress_id, []).append({
            'id': f'report-{log.id}', 'kind': '报工', 'operator': log.reported_by_name or '—',
            'at': log.reported_at, 'revoked': bool(log.revoked), 'revoked_at': log.revoked_at,
        })
    for log, name in skips:
        records.setdefault(log.progress_id, []).append({
            'id': f'skip-{log.id}', 'kind': '跳过', 'operator': name or '—',
            'at': log.created_at, 'revoked': bool(log.revoked), 'revoked_at': log.revoked_at,
        })
    result = []
    for progress, name in steps:
        events = sorted(records.get(progress.id, []), key=lambda row: (row['at'], row['id']))
        active = [row for row in events if not row['revoked']]
        status = '已报工' if any(row['kind'] == '报工' for row in active) else '已跳过' if active else '未报工'
        result.append({'progress_id': progress.id, 'step_order': progress.step_order,
                       'process_name': name, 'status': status, 'records': events})
    return {'unit_id': unit.id, 'unit_code': unit_display_code(item, unit.unit_no),
            'active': unit.status == 1, 'domestic_no': order.domestic_no, 'steps': result}
