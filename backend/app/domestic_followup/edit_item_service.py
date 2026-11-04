"""Keep item identities and downstream resolution/transfer history on edits."""
from app.domestic_followup import edit_task_service
from app.domestic_followup.models import DomesticFollowupItem as Item


def only_record(item):
    return item.status == "closed_no_action" and (item.resolution or "").startswith("仅记录")


def reconcile(db, followup, customer, incoming, existing, tasks, actor_id, old_date):
    by_id = {item.id: item for item in existing if item.status != "withdrawn"}
    ids = [item.id for item in incoming if item.id]
    if len(ids) != len(set(ids)) or any(item_id not in by_id for item_id in ids):
        raise ValueError("条目编号重复、已移除或不属于当前记录，请刷新")
    for old in by_id.values():
        if old.id in ids:
            continue
        if old.kind != "content" and old.status != "open" and not only_record(old):
            raise ValueError("正在处理或已处理的异常/意见不能删除，请保留条目后更正内容")
        old.status = "withdrawn"
        for task in tasks:
            if task.source_item_id == old.id and task.status == "todo":
                edit_task_service.cancel(task, actor_id, followup.id)
    seq = {"content": 0, "issue": 0, "suggestion": 0}
    for entry in incoming:
        if not entry.text.strip():
            raise ValueError("跟进条目内容不能为空")
        seq[entry.kind] += 1
        item = by_id.get(entry.id)
        new = item is None
        was_only = False
        if item is not None:
            if item.kind != entry.kind:
                raise ValueError("已有条目的类型不能更改，请新建对应条目")
            if entry.handler_user_id not in (None, item.handler_user_id):
                raise ValueError("处理人请通过转交操作调整")
            was_only = only_record(item)
            if entry.record_only != was_only and item.status not in (None, "open") and not was_only:
                raise ValueError("正在处理或已处理条目不能切换为仅记录")
        else:
            if entry.handler_user_id is not None:
                raise ValueError("新条目创建后请通过转交操作调整处理人")
            item = Item(followup_id=followup.id, customer_id=customer.id, kind=entry.kind,
                        origin=entry.origin, handler_user_id=followup.author_user_id if entry.kind != "content" else None)
            db.add(item)
        item.seq = seq[entry.kind]
        item.text = entry.text.strip()
        if entry.kind != "content":
            item.category = entry.category
            item.severity = entry.severity or "一般"
            if new or item.status == "open" or only_record(item):
                item.status = "closed_no_action" if entry.record_only else "open"
                item.resolution = "仅记录（跟进修改）" if entry.record_only else None
            db.flush()
            edit_task_service.sync_item(db, item, followup, customer, tasks, actor_id, old_date=old_date,
                                        allow_create=new or (was_only and not entry.record_only))
    db.flush()
