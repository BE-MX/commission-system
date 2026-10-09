"""Current employee authority at every installed linked workflow phase.

Provider evidence is read after the capture transaction ends. The ordinary
order executor owns durable original POST facts, even after authority is lost.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import logging
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import require_any_permission, require_permission
from app.core.time import beijing_now
from app.invoice import edit_authority, linked_sync_service as linked, order_sync_execution as orders
from app.invoice import linked_outbound_service, service, xiaoman_service
from app.portal.upstream_authority import begin_employee_document_write
from app.receipt import balance, remote

logger=logging.getLogger(__name__)


def entry(db,invoice_id,user,*permissions,any_permission=False):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409,"关联同步授权必须从新事务开始",headers={'Cache-Control':'private, no-store'})
    db.expire_all()
    try:current=begin_employee_document_write(db,user,*(permissions if not any_permission else ()))
    except SQLAlchemyError:_unavailable()
    installed=current is not user
    if not installed:
        checker=require_any_permission(*permissions) if any_permission else require_permission(permissions[0])
        checker(user)  # Verified exact pre-portal schema retains its original JWT rule.
    elif any_permission and 'super_admin' not in current.get('roles',[]):
        if not set(permissions).intersection(current.get('permissions',[])):
            raise HTTPException(403,"当前账号无权查看关联同步",headers={'Cache-Control':'private, no-store'})
    invoice=edit_authority.lock_document(db,invoice_id,force=installed)
    edit_authority._visible(db,invoice,current)
    return invoice,current,installed


def _phase(db,invoice_id,identity,user,token=None,*,active=True):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409,"关联同步阶段存在未提交事务")
    try:invoice,current=edit_authority.prepare_recovery(db,invoice_id,user,'invoice:sync')
    except SQLAlchemyError:_unavailable()
    row=db.get(linked.InvoiceLinkedSync,identity)
    if row is None or row.invoice_id!=invoice.id:raise HTTPException(404,"关联同步记录不存在")
    invoice,row=linked._lock(db,identity)
    if token is not None:
        if active:linked.ensure_running(db,invoice,identity,token)
        elif row.status not in {'done','manual'} or invoice.linked_sync_id is not None:
            raise HTTPException(409,"关联同步结果已变化，请读取原任务")
        if linked.snapshot(invoice)!=row.after or linked.latest(db,invoice.id).id!=identity:
            raise HTTPException(409,"关联同步对应的订单版本已变化，请核对原任务")
    return invoice,row,current


def _end_reads(db):
    if db.new or db.dirty or db.deleted:raise HTTPException(409,"外部取证产生了未提交业务修改")
    db.rollback();db.expire_all()


def _step(db,invoice_id,identity,user,token,key,result,expected=None):
    invoice,row,current=_phase(db,invoice_id,identity,user,token)
    if expected is not None and orders.capture(db,invoice,xiaoman_service.build_push_payload(db,invoice)[0])!=expected:
        raise HTTPException(409,"外部核对期间关联同步、订单或回款绑定已变化")
    row.steps={**row.steps,key:deepcopy(result)}
    db.commit()


def _capture(db,invoice_id,identity,user,token):
    invoice,row,current=_phase(db,invoice_id,identity,user,token)
    expected=orders.capture(db,invoice,xiaoman_service.build_push_payload(db,invoice)[0])
    frozen=_freeze(invoice)
    db.commit()
    return expected,frozen


def _freeze(invoice):
    frozen=SimpleNamespace(**{column.name:deepcopy(getattr(invoice,column.name)) for column in invoice.__table__.columns})
    frozen.items=[SimpleNamespace(**{column.name:deepcopy(getattr(item,column.name)) for column in item.__table__.columns}) for item in invoice.items]
    return frozen


def _finish(db,invoice_id,identity,user,token,status=None):
    invoice,row,current=_phase(db,invoice_id,identity,user,token)
    row.status=status or ('manual' if any(step['status']=='manual' for step in row.steps.values()) else 'done')
    row.run_token,row.lease_until=None,None
    if row.status in {'done','manual'}:invoice.linked_sync_id=None
    db.commit()


def _diagnose():
    failures=[]
    try:logger.warning('Linked synchronization evidence unavailable')
    except Exception as error:failures.append(error)
    try:print('[linked-sync] evidence unavailable',flush=True)
    except Exception as error:failures.append(error)
    return failures


def _unavailable():
    failures=_diagnose()
    error=HTTPException(503,'关联同步的当前授权暂不可确认，请稍后读取原任务',headers={'Cache-Control':'private, no-store'})
    if failures:raise error from ExceptionGroup('Linked diagnostics unavailable',failures)
    raise error from None


def _followup(db,invoice_id,identity,user):
    invoice,row,current=_phase(db,invoice_id,identity,user,token='completed',active=False)
    if row.steps['order']['status']!='done' or row.steps['outbound']['status']=='done':
        db.commit();return
    before=orders.state(row)
    frozen=_freeze(invoice)
    db.commit()
    from app.invoice import outbound_followup_service
    result=outbound_followup_service.safely_run(db,frozen,current,force_authority=True)
    _end_reads(db)
    invoice,row,current=_phase(db,invoice_id,identity,user,token='completed',active=False)
    if orders.state(row)!=before:raise HTTPException(409,"关联同步结果在出库核对期间已变化")
    row.steps={**row.steps,'outbound':result}
    row.status='done' if all(step['status']=='done' for step in row.steps.values()) else 'manual'
    db.commit()


def run(db,invoice_id,identity,user,*,recheck=False):
    try:
        invoice,row,current=_phase(db,invoice_id,identity,user)
        if row.status in {'done','manual'} and recheck:
            linked.ensure_idle(invoice)
            if row.steps['order']['status']!='done' or linked.snapshot(invoice)!=row.after or linked.latest(db,invoice.id).id!=identity:
                raise HTTPException(409,"原关联同步版本尚未完整核对，不能沿用任务")
            row.status='pending';invoice.linked_sync_id=identity
            row.steps={**row.steps,'outbound':{'status':'pending','message':'等待重新核对'},
                       'receipt':{'status':'pending','message':'等待重新核对'}}
        elif row.status in {'done','manual','uncertain'}:
            return row,invoice,current
        if row.status=='running':
            if not row.lease_until or row.lease_until<=beijing_now():row.status='uncertain'
            db.commit()
            invoice,row,current=_phase(db,invoice_id,identity,user)
            return row,invoice,current
        if invoice.linked_sync_id!=identity or linked.snapshot(invoice)!=row.after:
            raise HTTPException(409,"该修改版本已结束或订单已变化，请核对原任务")
        token=uuid4().hex
        row.status,row.run_token,row.lease_until='running',token,beijing_now()+timedelta(minutes=30)
        order_done=row.steps['order']['status']=='done'
        db.commit()
        if not order_done:
            _step(db,invoice_id,identity,user,token,'order',{'status':'sending','message':'正在更新原小满订单'})
            result=orders.run(db,invoice_id,user,linked_id=identity,linked_token=token,follow_outbound=False)
            _end_reads(db)
            if not result.get('ok'):
                invoice,row,current=_phase(db,invoice_id,identity,user,token)
                status='uncertain' if (result.get('okki_accepted') or result.get('inventory_pending')
                    or result.get('execution_changed') or invoice.sync_status=='sync_uncertain' or orders.facts.unresolved(db,invoice)) else 'failed'
                db.commit()
                _step(db,invoice_id,identity,user,token,'order',{'status':status,'message':'原订单同步未完成，请核对原任务'})
                _finish(db,invoice_id,identity,user,token,status)
                invoice,row,current=_phase(db,invoice_id,identity,user);return row,invoice,current
            _step(db,invoice_id,identity,user,token,'order',{'status':'done','message':'原小满订单已更新，库存收尾完成'})
        invoice,row,current=_phase(db,invoice_id,identity,user,token)
        outbound_done=row.steps['outbound']['status'] in {'done','manual'}
        db.commit()
        if not outbound_done:
            expected,frozen=_capture(db,invoice_id,identity,user,token)
            try:
                order=remote.read(db,'/v1/invoices/order/info',{'order_id':frozen.xiaoman_order_id})
                result=linked_outbound_service.summarize(db,frozen,order)
            except Exception:
                _diagnose();result={'status':'manual','message':'订单已同步，出库摘要暂不可用，请核对原单'}
            finally:_end_reads(db)
            _step(db,invoice_id,identity,user,token,'outbound',result,expected)
        expected,frozen=_capture(db,invoice_id,identity,user,token)
        try:live=remote.order_snapshot(db,frozen)
        except Exception:
            _diagnose();live=None
        finally:_end_reads(db)
        invoice,row,current=_phase(db,invoice_id,identity,user,token)
        if orders.capture(db,invoice,xiaoman_service.build_push_payload(db,invoice)[0])!=expected:
            raise HTTPException(409,"回款核对期间关联同步、订单或回款绑定已变化")
        if live is None:receipt={'status':'manual','message':'实际回款证据暂不可用，请人工核对原单'}
        else:
            try:
                summary=balance.calculate(db,invoice,live,current=True)
                effective,total=remote.money(summary['effective_amount']),remote.money(summary['total_amount'])
                receipt={'status':'done','message':'原回款金额与手续费保持不变；新增收款或退款须另行登记',
                    'balance':summary,'unpaid_amount':str(max(total-effective,0)),'overpaid_amount':str(max(effective-total,0))}
                if invoice.order_type!='presale' and (Decimal(summary['remaining_amount'])<0 or effective>total):
                    receipt.update(status='manual',message='已登记或生效金额超过新订单金额，请核对原回款；未修改实际收款')
            except ValueError:
                _diagnose()
                db.rollback();db.expire_all()
                receipt={'status':'manual','message':'实际回款余额待核验，请人工核对原单；未修改实际收款'}
                _step(db,invoice_id,identity,user,token,'receipt',receipt,expected)
                invoice,row,current=_phase(db,invoice_id,identity,user,token)
        row.steps={**row.steps,'receipt':receipt};db.commit()
        _finish(db,invoice_id,identity,user,token)
        _followup(db,invoice_id,identity,user)
        invoice,row,current=_phase(db,invoice_id,identity,user);return row,invoice,current
    except Exception:
        db.rollback()
        raise
