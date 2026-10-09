"""Enabled automatic outbound worker: current authority, unlocked I/O, original facts."""
import logging
from copy import deepcopy
from datetime import datetime,timedelta
from uuid import uuid4
from sqlalchemy import select,or_,func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased
from fastapi import HTTPException
from app.core.config import get_settings
from app.core.time import beijing_now,to_beijing_naive
from app.portal import authority
from app.portal.models import AuthorityBarrier
from app.portal.order_models import OrderRequest,Conversion
from app.invoice import outbound_mode,edit_authority,outbound_followup_execution as followup,okki_client
from app.invoice import outbound_create_plan as plan,outbound_create_facts as facts,outbound_task_service as tasks
from app.invoice.models import Invoice,OkkiOutboundTask,InvoiceSyncLog
from app.invoice.cancellation_service import audit
from app.receipt.models import Receipt,ReceiptIntent,ReceiptAttachment
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.shipping_inspection import audit_service,outbound_sync_plan as common
from app.shipping_inspection.outbound_prepare import current,row_state,reject
from app.shipping_inspection.outbound_execution import token

logger=logging.getLogger(__name__)
LOCK_NAME='ark-okki-outbound-poller'
MODE='outbound-worker-v1'
LEASE_MINUTES=5


def clear(db):db.rollback();db.expire_all()


def diagnose(db,phase,error):
    # Diagnostics are independent of supplier facts and original business errors.
    # Keep only controlled phase/sink and exception class; no original bodies.
    try:
        logger.warning('Outbound worker %s (%s)',phase,type(error).__name__)
    except Exception as failure:
        db.info.setdefault('outbound_worker_diagnostic_failures',[]).append({
            'phase':phase,'sink':'logger','error':type(failure).__name__})
    try:
        print('[outbound-worker] '+phase,flush=True)
    except Exception as failure:
        db.info.setdefault('outbound_worker_diagnostic_failures',[]).append({
            'phase':phase,'sink':'stdout','error':type(failure).__name__})


def enabled():
    settings=get_settings()
    return settings.PORTAL_ENABLED and settings.PORTAL_OUTBOUND_WORKER_ENABLED and settings.OKKI_OUTBOUND_AUTO_ENABLED


def local(db,invoice_id):
    if not enabled():reject(403,'当前后台自动出库执行已停用')
    actor_id=get_settings().PORTAL_OUTBOUND_WORKER_ACTOR_ID
    actor=current(db,{'sub':str(actor_id)})
    invoice=edit_authority.lock_document(db,invoice_id,force=True);edit_authority._visible(db,invoice,actor)
    if not invoice.outbound_auto_requested or invoice.order_type=='presale':reject(409,'此发票未明确请求整单自动出库')
    base,dto,rows,info,task=followup.capture(db,invoice,worker_capture=True)
    if info['latest_id'] is None or info['custom_missing']:reject(409,'缺少可信成功推单或真实产品绑定')
    # Task transitions are checked against an immutable START/checkpoint below.
    push_state=list(base[0]);push_state[3]=push_state[3][:3]
    relations=db.scalars(select(Conversion).where(Conversion.invoice_id==invoice.id).order_by(Conversion.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    requests=db.scalars(select(OrderRequest).where(OrderRequest.id.in_([row.request_id for row in relations]))
        .order_by(OrderRequest.id).with_for_update().execution_options(populate_existing=True)).all()
    financial=[];proof_ids=set()
    for model in (Receipt,ReceiptIntent,InvoiceAllocation):
        values=db.scalars(select(model).where(model.invoice_id==invoice.id).order_by(model.id)
            .with_for_update().execution_options(populate_existing=True)).all()
        financial.append(tuple(row_state(row) for row in values))
        if model is ReceiptIntent:
            for row in values:proof_ids.update(row.attachment_ids or [])
    proofs=db.scalars(select(ReceiptAttachment).where(or_(ReceiptAttachment.invoice_id==invoice.id,
        ReceiptAttachment.id.in_(proof_ids))).order_by(ReceiptAttachment.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    deletion=None
    if task and (task.reason or '').startswith('regenerate:'):
        generation=common.canonical_identity((task.reason or '').split(' ',1)[0][11:])
        if generation!=str(info['latest_id']):reject(409,'再生成代次不属于当前成功推单')
        candidates=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope=='outbound-delete',
            ShippingOperationEvent.action=='outbound_deleted').order_by(ShippingOperationEvent.id.desc())
            .with_for_update().execution_options(populate_existing=True)).all()
        for candidate in candidates:
            data=candidate.payload or {}
            if str(invoice.xiaoman_order_id) not in list(map(str,data.get('order_ids',[]))) or str(task.id) not in [str(row.get('id')) for row in data.get('tasks',[])]:continue
            identity=common.canonical_identity(data['outbound_invoice_id'])
            if candidate.request_id!=identity or candidate.outbound_record_id!=identity:reject(409,'原删除证据身份不一致')
            common.index(data['tasks'],'id')
            for value in data['order_ids']:common.canonical_identity(value)
            latest=db.get(InvoiceSyncLog,info['latest_id'])
            if latest.created_at<=candidate.created_at:reject(409,'原删除后没有新的成功推单')
            deletion=candidate;break
        if deletion is None:reject(409,'再生成缺少永久原删除证据')
    binding=(tuple(push_state),base[2:],row_state(invoice),tuple(row_state(item) for item in invoice.items),
        tuple(financial),tuple(row_state(row) for row in proofs),tuple(row_state(row) for row in relations),
        tuple(row_state(row) for row in requests),row_state(deletion))
    state=facts.get(db,facts.STATE,str(task.id)) if task else None
    metadata={'invoice_no':invoice.invoice_no,'remark':invoice.remark or '',
              'lineage':[{'request_id':row.request_id,'conversion_id':row.id} for row in relations],
              'regeneration':deletion is not None,'deleted_outbound_id':deletion.request_id if deletion else None}
    return actor,invoice,task,state,binding,dto,rows,metadata


def expired(attempt):
    return to_beijing_naive(datetime.fromisoformat(attempt.data['started_at']))+timedelta(minutes=LEASE_MINUTES)<=beijing_now()


def owned(db,task,state,binding,attempt,*,sender=False):
    facts.validate(db,attempt);data=attempt.data
    if any(other.nonce!=attempt.nonce for other in facts.unresolved(db,data['invoice_id'])):
        reject(409,'其他原代次后台外发事实尚未核对')
    if (task is None or task.id!=data['task_id'] or str(task.order_id)!=data['order_id']
            or common.digest(binding)!=data['binding_fingerprint'] or state is None
            or state.operator_user_id!=data['actor_id'] or state.source!='outbound_worker'
            or state.operator_name!=facts.get(db,facts.START,attempt.nonce).operator_name
            or (state.payload or {}).get('nonce')!=attempt.nonce):
        reject(409,'原后台任务或完整商业绑定已变化')
    expected=data['task_fingerprint'];action='create_pending';result={'started_at':data['started_at']}
    checkpoint=(state.payload or {}).get('checkpoint')
    if checkpoint:
        scope=(state.payload or {}).get('checkpoint_scope')
        if scope not in (facts.CHECK,facts.FINISH):reject(409,'原后台核对记录身份无效')
        record=facts.get(db,scope,checkpoint)
        if record is None or record.payload!={'nonce':attempt.nonce,'invoice_id':data['invoice_id'],
                'task_id':data['task_id'],'start_fingerprint':common.digest(data)}:
            reject(409,'原后台核对记录缺失')
        expected=record.result['task_fingerprint'];action=record.result['state_action'];result=record.result['state_result']
    elif facts.get(db,facts.SEND,attempt.nonce) is not None:action='create_sending'
    if (common.digest(row_state(task))!=expected or state.action!=action or state.result!=result
            or state.payload!={'protocol':1,'nonce':attempt.nonce,
                **({'checkpoint':checkpoint,'checkpoint_scope':scope} if checkpoint else {})}):
        reject(409,'原后台任务执行代次或收尾记录已变化')
    if sender and expired(attempt):reject(409,'原后台发送租约已过期，请核对原单')


def evidence(db,dto,rows,metadata,*,original=None):
    try:
        order=followup.read_order(db,dto,rows)
        if original is not None and order!=original:reject(409,'原供应商订单已变化')
        related=followup.legacy.linked_outbound_service.find_related(db,order)
        if not isinstance(related,list):reject(503,'原关联扫描证据缺失')
        for detail in related:plan.isolated(detail,common.canonical_identity(order['order_id']))
        selection=None
        if not related:
            for serial in (metadata['invoice_no'],metadata['invoice_no']+' ['+str(order['order_id'])+']'):
                occupant=okki_client.find_outbound_by_serial(db,serial)
                if occupant is None:selection=serial;break
                try:occupied=plan.occupied_orders(occupant,serial)
                except (ValueError,TypeError,KeyError):reject(503,'原占号详情证据不完整，禁止选择备用单号')
                if common.canonical_identity(order['order_id']) in occupied:
                    if len(occupied)!=1:reject(409,'原占号包含其他订单，禁止新建出库')
                    plan.isolated(occupant,common.canonical_identity(order['order_id']))
                    if not metadata['regeneration'] or common.canonical_identity(occupant['outbound_invoice_id'])!=metadata['deleted_outbound_id']:
                        reject(409,'原单号详情仍有关联，不能由空索引推断可新建')
                    # Verified deletion may leave a readable removed serial; choose a vacant serial.
                    continue
            if selection is None:reject(409,'可用原出库单号无法确认')
        payload=plan.build(order,metadata['invoice_no'],metadata['remark'],selection)
        shortages=followup.legacy._stock_shortages(db,order) if not related else []
        if followup.read_order(db,dto,rows)!=order:reject(409,'原供应商订单回读已变化')
        again=followup.legacy.linked_outbound_service.find_related(db,order)
        if again!=related:reject(409,'原关联出库回读已变化')
        if not related and okki_client.find_outbound_by_serial(db,payload['serial_id']) is not None:
            reject(409,'原出库单号已被占用')
        return order,related,payload,shortages
    finally:clear(db)


def checkpoint(db,actor,task,state,attempt,status,message,*,verified=None,read_key=None,finished=False):
    task.status=status;task.last_error=None if finished else message
    task.processed_at=beijing_now();task.updated_at=beijing_now()
    state.action='create_done' if finished else 'create_uncertain'
    state.result={'started_at':attempt.data['started_at'],'message':message}
    db.flush();db.refresh(task)
    result={'task_fingerprint':common.digest(row_state(task)),'state_action':state.action,
        'state_result':deepcopy(state.result),'finished_by':actor['id'],'read_key':read_key,
        'verified_fingerprint':common.digest(verified),'facts_fingerprint':facts.fingerprint(db,attempt,risk=True)}
    scope=facts.FINISH if finished else facts.CHECK
    key=facts.finish_key(db,attempt) if finished else str(uuid4())
    facts.append(db,scope,key,attempt,result)
    state.payload={'protocol':1,'nonce':attempt.nonce,'checkpoint':key,'checkpoint_scope':scope}


def verify(db,invoice_id,attempt,*,sender=False):
    actor,invoice,task,state,binding,dto,rows,metadata=local(db,invoice_id)
    owned(db,task,state,binding,attempt,sender=sender)
    state_snapshot=row_state(state);expected_facts=facts.fingerprint(db,attempt)
    before_done=state.action=='create_done'
    fact=facts.get(db,facts.FACT,attempt.nonce)
    expected_id=fact.result.get('outbound_invoice_id') if fact and fact.result['result_class']=='accepted' else None
    db.commit();clear(db)
    verified=None
    try:
        order=followup.read_order(db,dto,rows)
        if order!=attempt.data['order']:reject(409,'核对时原供应商订单已变化')
        related=followup.legacy.linked_outbound_service.find_related(db,order)
        if not isinstance(related,list):reject(503,'原关联扫描证据缺失')
        if len(related)==1:
            verified=plan.verify(related[0],attempt.data['payload'],attempt.data['order_id'],expected_id)
            detail=followup.legacy.remote.read(db,'/v1/invoices/outbound/info',{'outbound_invoice_id':verified['outbound_invoice_id']})
            if detail!=verified:reject(409,'原出库单回读已变化')
        if followup.read_order(db,dto,rows)!=order:reject(409,'原订单回读已变化')
    except (HTTPException,okki_client.OkkiApiError,ValueError,TypeError,KeyError) as error:
        diagnose(db,'readback_unknown',error)
        verified=None
    finally:clear(db)
    facts.original_lock(db,attempt)
    changed=facts.fingerprint(db,attempt)!=expected_facts
    read_key=facts.observe(db,attempt,'verified' if verified else 'unknown',verified,reading=True)
    observed_facts=facts.fingerprint(db,attempt);db.commit();clear(db)
    if changed:reject(409,'原后台出库事实集合已变化，请重新核对')
    actor,invoice,task,state,binding,_,_,_=local(db,invoice_id)
    owned(db,task,state,binding,attempt,sender=sender)
    if row_state(state)!=state_snapshot or facts.fingerprint(db,attempt)!=observed_facts:
        reject(409,'核对期间原后台任务或事实集合已变化')
    if before_done:
        if verified is None:reject(409,'迟到事实与原已完成出库不一致')
        # Review a late POST observation without repeating task or audit mutations.
        previous=facts.get(db,facts.FINISH,state.payload['checkpoint'])
        result={**deepcopy(previous.result),'read_key':read_key,'finished_by':actor['id'],
                'facts_fingerprint':facts.fingerprint(db,attempt,risk=True),
                'verified_fingerprint':common.digest(verified)}
        key=facts.finish_key(db,attempt);facts.append(db,facts.FINISH,key,attempt,result)
        state.payload={**state.payload,'checkpoint':key}
    else:
        checkpoint(db,actor,task,state,attempt,'done' if verified else 'uncertain',
            'Original outbound verified' if verified else 'Original outbound result requires review',
            verified=verified,read_key=read_key,finished=verified is not None)
        if verified:audit(db,invoice,'outbound_created',actor['id'],{'task_id':task.id,'original_order_id':attempt.data['order_id']})
    db.commit();clear(db)
    return {'status':'done' if verified else 'uncertain','posted':False}


def send(db,invoice_id,attempt,access_token):
    actor,_,task,state,binding,dto,rows,metadata=local(db,invoice_id)
    owned(db,task,state,binding,attempt,sender=True)
    if actor['id']!=attempt.data['actor_id']:reject(403,'原发送执行账号已变化')
    db.commit();clear(db)
    order,related,payload,shortages=evidence(db,dto,rows,metadata,original=attempt.data['order'])
    if related or shortages or payload!=attempt.data['payload']:reject(409,'原发送前出库或库存证据已变化')
    actor,_,task,state,binding,_,_,_=local(db,invoice_id)
    owned(db,task,state,binding,attempt,sender=True)
    if actor['id']!=attempt.data['actor_id'] or facts.get(db,facts.SEND,attempt.nonce) is not None:
        reject(409,'原后台发送已开始，禁止重发')
    facts.append(db,facts.SEND,attempt.nonce,attempt,{})
    state.action='create_sending';db.commit();clear(db)
    result=None;result_class='unknown'
    try:
        if db.in_transaction() or db.new or db.dirty or db.deleted:raise RuntimeError('Worker POST has a local transaction')
        result=okki_client._post_json('/v1/invoices/outbound/push',access_token,attempt.data['payload'],context='后台出库')
        if result is None:result_class='auth_rejected'
        elif isinstance(result,dict) and result.get('serial_id')==attempt.data['payload']['serial_id']:
            common.canonical_identity(result['outbound_invoice_id']);result_class='accepted'
    except (okki_client.OkkiApiError,ValueError,TypeError,KeyError) as error:
        diagnose(db,'post_unknown',error)
    finally:clear(db)
    facts.observe(db,attempt,result_class,result);db.commit();clear(db)
    return {**verify(db,invoice_id,attempt,sender=True),'posted':True}


def process(db,invoice_id):
    try:
        actor,invoice,task,state,binding,dto,rows,metadata=local(db,invoice_id)
        pending=facts.unresolved(db,invoice_id)
        if pending:
            if len(pending)!=1 or state is None or (state.payload or {}).get('nonce')!=pending[0].nonce:
                reject(409,'原后台跨代次外发尚未核对，禁止新建出库')
            attempt=pending[0];owned(db,task,state,binding,attempt)
            active=not expired(attempt);sent=facts.get(db,facts.SEND,attempt.nonce) is not None
            db.commit();clear(db)
            if active:return {'status':'processing','posted':False}
            if not sent:
                actor,_,task,state,binding,_,_,_=local(db,invoice_id)
                owned(db,task,state,binding,attempt)
                if not expired(attempt) or facts.get(db,facts.SEND,attempt.nonce) or facts.get(db,facts.FACT,attempt.nonce):
                    reject(409,'原后台发送事实已变化')
                checkpoint(db,actor,task,state,attempt,'pending','Expired claim proved not sent',finished=True)
                db.commit();clear(db)
                return process(db,invoice_id)
            return verify(db,invoice_id,attempt)
        if task is None:
            task=tasks.enqueue_outbound_task(db,invoice)
            audit(db,invoice,'outbound_queue',actor['id'],{'task_id':task.id,'original_order_id':str(invoice.xiaoman_order_id)})
            db.commit();clear(db)
            return process(db,invoice_id)
        if task.status in ('running','uncertain'):
            reject(409,'历史后台任务缺少可信原发送记录，请人工核对')
        if task.status not in ('pending','waiting_stock','failed'):
            db.commit();clear(db);return {'status':task.status,'posted':False}
        now=beijing_now()
        if task.status=='waiting_stock' and task.updated_at+timedelta(minutes=15)>now:
            db.commit();clear(db);return {'status':'waiting_stock','posted':False}
        if task.status=='failed' and (task.attempts>=5 or task.updated_at+timedelta(minutes=(task.attempts+1)*5)>now):
            db.commit();clear(db);return {'status':'failed','posted':False}
        captured=(binding,row_state(task));db.commit();clear(db)
        order,related,payload,shortages=evidence(db,dto,rows,metadata)
        access_token=token(db) if not related and not shortages else None
        actor,invoice,task,state,binding,_,_,metadata=local(db,invoice_id)
        if (binding,row_state(task))!=captured or facts.unresolved(db,invoice_id):
            reject(409,'取证期间当前订单、任务或原事实已变化')
        if related or shortages:
            task.status='skipped' if related else 'waiting_stock'
            generation=(task.reason or '').split(' ',1)[0] if (task.reason or '').startswith('regenerate:') else None
            task.reason='Existing outbound requires manual handling' if related else generation
            task.last_error=None if related else 'Insufficient destination warehouse stock'
            task.updated_at=beijing_now()
            audit(db,invoice,'outbound_queue',actor['id'],{'task_id':task.id,'status':task.status})
            status=task.status;db.commit();clear(db);return {'status':status,'posted':False}
        task.status='running';task.attempts+=1;task.last_error=None;task.updated_at=beijing_now()
        db.flush();db.refresh(task)
        nonce=str(uuid4());data={'protocol':1,'nonce':nonce,'invoice_id':invoice.id,'task_id':task.id,
            'order_id':common.canonical_identity(task.order_id),'actor_id':actor['id'],'lineage':metadata['lineage'],
            'binding_fingerprint':common.digest(binding),'task_fingerprint':common.digest(row_state(task)),
            'order':order,'payload':payload,'payload_fingerprint':common.digest(payload),
            'started_at':beijing_now().isoformat()}
        attempt=facts.Attempt(nonce,data);original=facts.append(db,facts.START,nonce,attempt,{})
        if state is None:
            state=audit_service.record(db,'create_pending',actor['id'],'create:'+str(invoice_id),
                context={'scope':facts.STATE,'source':'outbound_worker'},request_id=str(task.id))
        state.action='create_pending';state.payload={'protocol':1,'nonce':nonce};state.result={'started_at':data['started_at']}
        state.operator_user_id=state.login_user_id=actor['id']
        state.operator_name=original.operator_name;state.login_name=original.login_name
        db.commit();clear(db)
        return send(db,invoice_id,attempt,access_token)
    except HTTPException:clear(db);raise
    except (okki_client.OkkiApiError,OverflowError) as error:
        clear(db)
        diagnose(db,'supplier_unavailable',error)
        reject(503,'后台出库供应商证据暂不可确认，禁止重发')
    except (ValueError,KeyError,TypeError) as error:
        diagnose(db,'invalid_binding',error)
        clear(db);reject(409,'后台出库原资料或执行绑定不可确认')
    except SQLAlchemyError as error:
        clear(db)
        diagnose(db,'commit_unconfirmed',error)
        reject(503,'后台出库提交暂不可确认，请核对原任务，禁止重发')


def install_mode(db):
    return outbound_mode.establish_under_fence(db)


def run_once(factory):
    if not get_settings().PORTAL_ENABLED:return {'status':'disabled','processed':0}
    with factory() as db:
        # Shared advisory executor fence; no authority/PI/task row lock crosses I/O.
        with outbound_mode.executor_fence(db) as acquired:
            if not acquired:return {'status':'busy','processed':0}
            try:
                install_mode(db)
                if not enabled():return {'status':'disabled','processed':0}
                # Each bounded page advances even when every action is deferred/in flight.
                # A fixed high-water mark prevents new arrivals extending this tick forever.
                ceiling=db.scalar(select(func.max(Invoice.id))) or 0;clear(db)
                cursor=0;completed=0
                while cursor<ceiling:
                    later=aliased(ShippingOperationEvent)
                    unfinished=~select(later.id).where(later.scope==facts.FINISH,
                        later.outbound_record_id==ShippingOperationEvent.outbound_record_id,
                        later.payload['nonce'].as_string()==ShippingOperationEvent.payload['nonce'].as_string(),
                        later.id>ShippingOperationEvent.id).exists()
                    late=select(ShippingOperationEvent.id).where(ShippingOperationEvent.scope==facts.FACT,
                        ShippingOperationEvent.outbound_record_id==func.concat('create:',Invoice.id),unfinished).exists()
                    ordinary=or_(OkkiOutboundTask.id.is_(None),
                        OkkiOutboundTask.status.in_(['pending','waiting_stock','failed','running','uncertain']))
                    candidates=db.scalars(select(Invoice.id).outerjoin(OkkiOutboundTask,OkkiOutboundTask.invoice_id==Invoice.id)
                        .where(Invoice.id>cursor,Invoice.id<=ceiling,Invoice.outbound_auto_requested==1,
                               Invoice.sync_status=='synced',Invoice.order_type!='presale',or_(ordinary,late))
                        .order_by(Invoice.id).limit(20)).all();clear(db)
                    if not candidates:break
                    cursor=candidates[-1]
                    for invoice_id in candidates:
                        try:process(db,invoice_id);completed+=1
                        except HTTPException as error:
                            diagnose(db,'action_deferred',error)
                return {'status':'processed','processed':completed}
            finally:
                outbound_mode.rollback_owned(db)
