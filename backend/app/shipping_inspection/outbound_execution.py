"""Current-authorized outbound claims, lock-free POST, original facts and verification."""
import logging
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import okki_client
from app.portal.access_policy import employee_principal
from app.portal.errors import PortalError
from app.shipping_inspection import outbound_prepare as prepare, outbound_facts as facts
from app.shipping_inspection import outbound_sync_plan as plans, outbound_sync_state as state

logger=logging.getLogger(__name__)


def unavailable():
    logger.warning('Outbound execution requires original result recovery')
    print('[outbound-execution] original result recovery required',flush=True)
    prepare.reject(503,'原出库执行暂不可确认，请读取原任务，禁止重复外发')


def clear(db):
    db.rollback();db.expire_all()


def local(db,record,user,warehouse,*,attempt=None,actions=None,sender=False):
    actor=prepare.current(db,user,warehouse)
    original=prepare.mirror(db,record,actor,warehouse)
    invoice,event,business,binding,local_data=prepare.capture(db,original,actor,executing=True)
    if attempt:
        facts.validate(db,attempt)
        if (invoice.id!=attempt.data['invoice_id'] or original!=attempt.data['record']
                or plans.digest(business)!=attempt.data['binding_fingerprint']
                or event is None or event.payload!=facts.event_payload(attempt)
                or event.operator_user_id!=attempt.data['actor_id']
                or event.source!=attempt.data['source']
                or event.result.get('started_at')!=attempt.data['started_at']
                or actions and event.action not in actions):
            prepare.reject(409,'原出库执行权或完整本地绑定已变化')
        if sender and facts.expired(attempt):prepare.reject(409,'原发送租约已过期，请核对原任务')
    return actor,original,invoice,event,business,binding,local_data


def token(db):
    try:
        value=okki_client.ensure_access_token(db)
        db.commit()  # Credential cache alone, without authority/document/inspection locks.
        return value
    except (ValueError,okki_client.OkkiApiError,SQLAlchemyError):unavailable()
    finally:clear(db)


def before_send(db,attempt,local_data):
    """Only read provider evidence; caller has committed all local locks."""
    from app.invoice.outbound_followup_execution import read_order
    from app.shipping_inspection import outbound_sync_service as legacy
    try:
        plan=attempt.data['plan']
        order=read_order(db,local_data['dto'],local_data['products'])
        if order!=plan['order']:prepare.reject(409,'发送前原供应商订单已变化')
        related=legacy.linked_outbound_service.find_related(db,order)
        if not isinstance(related,list) or any(not isinstance(row,dict) or not row.get('outbound_invoice_id') for row in related):
            prepare.reject(503,'发送前关联出库证据不完整')
        if len(related)!=1 or plans.canonical_identity(related[0]['outbound_invoice_id'])!=plans.canonical_identity(plan['before']['outbound_invoice_id']):
            prepare.reject(409,'发送前原出库关联已变化')
        expected=attempt.data.get('repair_before') or plan['before']
        if prepare.read_outbound(db,expected['outbound_invoice_id'])!=expected:
            prepare.reject(409,'发送前原出库证据已变化')
        if plan['serial_changed']:
            occupant=okki_client.find_outbound_by_serial(db,plan['serial_after'])
            if occupant and plans.canonical_identity(occupant['outbound_invoice_id'])!=plans.canonical_identity(expected['outbound_invoice_id']):
                prepare.reject(409,'发送前新出库单号已被占用')
        if read_order(db,local_data['dto'],local_data['products'])!=order or prepare.read_outbound(db,expected['outbound_invoice_id'])!=expected:
            prepare.reject(409,'发送前订单回读已变化')
    except HTTPException:raise
    except (ValueError,KeyError,TypeError):prepare.reject(503,'发送前原出库证据不完整')
    except okki_client.OkkiApiError:unavailable()
    finally:clear(db)


def response(db,record,user,invoice_id,warehouse,result):
    prepare.authorize_response(db,record,user,invoice_id,warehouse)
    return result


def claim(db,record,user,warehouse,plan,binding,auto_recall,source,payload=None,parent=None,repair_step=None):
    actor,original,invoice,event,business,current_binding,_=local(db,record,user,warehouse)
    if (current_binding!=binding or plans.digest(business)!=plan['local_binding_fingerprint']
            or event is None or event.action in state.ACTIVE):
        prepare.reject(409,'凭证获取期间原出库或本地资料已变化')
    attempt=facts.start(db,invoice.id,original,actor['id'],plan,payload or plan['payload'],
                        auto_recall,source,warehouse,repair_step,parent)
    event.action='sync_pending';event.payload=facts.event_payload(attempt);event.source=source
    event.operator_user_id=event.login_user_id=actor['id']
    event.operator_name=event.login_name=facts.get(db,facts.START,attempt.nonce).operator_name
    event.result={**(event.result or {}),'started_at':attempt.data['started_at']}
    db.commit();clear(db)
    return attempt


def post(db,attempt,access_token):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        prepare.reject(409,'出库外发必须在本地事务结束后执行')
    outcome='unknown';result=None
    try:
        result=okki_client._post_json('/v1/invoices/outbound/push',access_token,
                                     attempt.data['payload'],context='同步原出库单')
        if result is None:
            outcome='auth_rejected'
        elif isinstance(result,dict) and result.get('outbound_invoice_id') is not None:
            if plans.canonical_identity(result['outbound_invoice_id'])==plans.canonical_identity(attempt.data['record']['outbound_invoice_id']):
                outcome='accepted'
    except (okki_client.OkkiApiError,ValueError):
        logger.warning('Outbound POST result is uncertain')
        print('[outbound-execution] POST result uncertain',flush=True)
    finally:clear(db)
    # No current employee/scope or mutable task check: preserve only this immutable original fact.
    facts.observe(db,attempt,outcome,result)
    db.commit();clear(db)
    return outcome


def send_attempt(db,record,user,warehouse,attempt,access_token,local_data):
    before_send(db,attempt,local_data)
    _,_,_,event,_,_,_=local(db,record,user,warehouse,attempt=attempt,actions=('sync_pending',),sender=True)
    if facts.get(db,facts.SEND,attempt.nonce) is not None:prepare.reject(409,'原发送授权已使用，禁止重复外发')
    facts.mark_sending(db,attempt)
    event.action='sync_sending'
    db.commit();clear(db)  # Unknown ACK stops POST; recovery will use the original nonce/GET only.
    post(db,attempt,access_token)
    return verify(db,record,user,warehouse,attempt,sender=True)


def verify(db,record,user,warehouse,attempt,*,sender=False):
    from app.shipping_inspection import outbound_sync_service as legacy
    _,_,invoice,event,_,_,_=local(db,record,user,warehouse,attempt=attempt,
        actions=('sync_sending','sync_uncertain'),sender=sender)
    observed_event=prepare.row_state(event)
    original_chain=facts.chain(db,attempt)
    before_facts={item.nonce:facts.fingerprint(db,item) for item in original_chain}
    db.commit();clear(db)
    after=None;verified=False;partial=False
    try:
        after=prepare.read_outbound(db,attempt.data['record']['outbound_invoice_id'])
        try:
            plans.verify(attempt.data['plan']['before'],after,attempt.data['plan']);verified=True
        except (ValueError,KeyError,TypeError):
            try:plans.missing_only(attempt.data['plan']['before'],after,attempt.data['plan']);partial=True
            except (ValueError,KeyError,TypeError):
                logger.warning('Outbound readback does not match the original plan')
                print('[outbound-execution] readback differs',flush=True)
    except (HTTPException,okki_client.OkkiApiError):
        logger.warning('Outbound readback unavailable')
        print('[outbound-execution] readback unavailable',flush=True)
    finally:clear(db)
    # Freeze the set BEFORE GET; newly arrived original facts invalidate that evidence.
    facts.original_lock(db,attempt)
    changed_facts=any(facts.fingerprint(db,item)!=before_facts[item.nonce] for item in facts.chain(db,attempt))
    facts.observe(db,attempt,'verified' if verified else 'partial' if partial else 'unknown',after,reading=True)
    chain=facts.chain(db,attempt)
    expected_facts={item.nonce:facts.fingerprint(db,item) for item in chain}
    db.commit();clear(db)
    if changed_facts:prepare.reject(409,'回读期间新的原出库事实已到达，请重新核对')
    actor,_,invoice,event,_,_,_=local(db,record,user,warehouse,attempt=attempt,
        actions=('sync_sending','sync_uncertain'),sender=sender)
    if prepare.row_state(event)!=observed_event:prepare.reject(409,'回读期间原出库任务已变化')
    if any(facts.fingerprint(db,item)!=expected_facts[item.nonce] for item in facts.chain(db,attempt)):
        prepare.reject(409,'回读期间原出库事实集合已变化')
    if not verified:
        event.action='sync_uncertain'
        event.result={**(event.result or {}),'message':'原出库结果待核对；不会重复发送'}
        original_fact=facts.get(db,facts.FACT,attempt.nonce)
        repairable=partial and original_fact is not None and original_fact.result.get('result_class')=='accepted'
        result={'status':'sync_uncertain','recover':True,'repairable':repairable,
                'message':event.result['message']}
    else:
        result=legacy._finish_verified(db,event,attempt.data['plan'],after,commit_result=False,finisher_id=actor['id'])
        if result['status']=='sync_done':
            # Inspection/recall/overlay and original FINISH commit atomically.
            db.flush()
            finished_record=prepare.mirror(db,record,actor,warehouse)
            _,_,finished_business,_,_=prepare.capture(db,finished_record,actor,executing=True)
            for item in chain:
                facts.append(db,facts.FINISH,item.nonce,item,facts.identity(item),
                    {'facts_fingerprint':facts.fingerprint(db,item,include_reads=False),
                     'evidence_fingerprint':expected_facts[item.nonce],'verified_fingerprint':plans.digest(after),
                     'after_binding_fingerprint':plans.digest(finished_business),
                     'event_result_fingerprint':plans.digest(event.result),'result':deepcopy(result),
                     'finished_by':actor['id']})
    invoice_id=invoice.id
    db.commit();clear(db)
    return response(db,record,user,invoice_id,warehouse,result)


def recover(db,record,user,warehouse,event,attempt,*,repair=False,check_only=False):
    action=event.action
    sent=facts.get(db,facts.SEND,attempt.nonce) is not None
    if action in ('sync_pending','sync_sending') and not facts.expired(attempt):
        invoice_id=attempt.data['invoice_id'];db.commit();clear(db)
        return response(db,record,user,invoice_id,warehouse,
            {'status':action,'recover':True,'message':'原发送仍在处理中，不会重复外发'})
    if action=='sync_pending' and not sent:
        db.commit();clear(db)
        _,_,_,event,_,_,_=local(db,record,user,warehouse,attempt=attempt,actions=('sync_pending',))
        if not facts.expired(attempt) or facts.get(db,facts.SEND,attempt.nonce) is not None:
            prepare.reject(409,'原发送状态或租约已变化')
        if facts.get(db,facts.FACT,attempt.nonce) is not None:prepare.reject(409,'原任务有发送事实，禁止作为未发送取消')
        event.action='sync_failed';event.result={**(event.result or {}),'message':'原准备过期且未获发送授权，请重新预览'}
        facts.append(db,facts.FINISH,attempt.nonce,attempt,facts.identity(attempt),
                     {'facts_fingerprint':facts.fingerprint(db,attempt,include_reads=False),'not_sent':True})
        invoice_id=attempt.data['invoice_id'];db.commit();clear(db)
        return response(db,record,user,invoice_id,warehouse,
            {'status':'sync_failed','requires_preview':True,'message':'上次任务未发送，请重新预览'})
    if action=='sync_pending':prepare.reject(409,'原发送授权与任务状态不一致，禁止再次发送')
    db.commit();clear(db)
    result=verify(db,record,user,warehouse,attempt)
    if repair and not check_only and result.get('repairable'):
        return repair_missing(db,record,user,warehouse,attempt)
    return result


def repair_missing(db,record,user,warehouse,previous):
    """Each proved new missing row receives a new nonce; never replay an uncertain step."""
    from app.invoice.outbound_followup_execution import read_order
    from app.shipping_inspection import outbound_sync_service as legacy
    _,_,invoice,event,_,_,local_data=local(db,record,user,warehouse,attempt=previous,actions=('sync_uncertain',))
    original_fact=facts.get(db,facts.FACT,previous.nonce)
    if original_fact is None or original_fact.result.get('result_class')!='accepted':
        prepare.reject(409,'原发送仍无明确接受回执，禁止自动补齐')
    baseline=prepare.row_state(event)
    chain=facts.chain(db,previous)
    baseline_facts={item.nonce:facts.fingerprint(db,item) for item in chain}
    db.commit();clear(db)
    plan=previous.data['plan']
    try:
        order=read_order(db,local_data['dto'],local_data['products'])
        if order!=plan['order']:prepare.reject(409,'补齐前原订单商业资料已变化')
        related=legacy.linked_outbound_service.find_related(db,order)
        if not isinstance(related,list) or any(not isinstance(row,dict) or not row.get('outbound_invoice_id') for row in related):
            prepare.reject(503,'补齐前关联出库证据不完整')
        if len(related)!=1 or plans.canonical_identity(related[0]['outbound_invoice_id'])!=plans.canonical_identity(previous.data['record']['outbound_invoice_id']):
            prepare.reject(409,'补齐前原出库关联已变化')
        current=prepare.read_outbound(db,previous.data['record']['outbound_invoice_id'])
        missing=plans.missing_only(plan['before'],current,plan)
        prior=previous.data['repair_step']
        if prior and (prior['order_record_id'] in missing or len(missing)>=prior['missing_before']):
            prepare.reject(409,'原补齐明细仍未出现，禁止重复推送')
        identity=missing[0];actual=plans.index(current['record_list'],'order_record_id')
        expected=plans.index(plan['expected'],'order_record_id')
        rows=[{**row,'outbound_record_id':actual[key]['outbound_record_id'],
               'cost_unit_price_rmb':actual[key].get('cost_unit_price_rmb',0)} if key in actual else deepcopy(row)
              for key,row in expected.items() if key in actual or key==identity]
        payload={'outbound_invoice_id':current['outbound_invoice_id'],'handler':[str(row['user_id']) for row in current['handler_info']],
                 'remark':plan['remark_after'],'record_list':rows}
        if not payload['handler']:prepare.reject(409,'原出库处理人缺失')
        if prepare.read_outbound(db,current['outbound_invoice_id'])!=current or read_order(db,local_data['dto'],local_data['products'])!=order:
            prepare.reject(409,'补齐证据回读已变化')
    except (ValueError,KeyError,TypeError):prepare.reject(409,'原单不是可安全补齐的新增缺行')
    except okki_client.OkkiApiError:unavailable()
    finally:clear(db)
    access_token=token(db)
    actor,original,invoice,event,_,_,_=local(db,record,user,warehouse,attempt=previous,actions=('sync_uncertain',))
    if prepare.row_state(event)!=baseline or any(facts.fingerprint(db,item)!=baseline_facts[item.nonce] for item in facts.chain(db,previous)):
        prepare.reject(409,'补齐准备期间原任务或事实集合已变化')
    # Preserve the original full plan, target and cumulative inspection state.
    attempt=facts.start(db,invoice.id,original,actor['id'],plan,payload,previous.data['auto_recall'],
        previous.data['source'],warehouse,{'order_record_id':identity,'missing_before':len(missing)},previous.nonce,current)
    event.action='sync_pending';event.payload=facts.event_payload(attempt)
    event.operator_user_id=event.login_user_id=actor['id']
    event.operator_name=event.login_name=facts.get(db,facts.START,attempt.nonce).operator_name
    event.result={**(event.result or {}),'started_at':attempt.data['started_at']}
    db.commit();clear(db)
    return send_attempt(db,record,user,warehouse,attempt,access_token,local_data)



def review_finished(db,record,user,warehouse,attempt):
    def capture():
        actor=prepare.current(db,user,warehouse)
        original=prepare.mirror(db,record,actor,warehouse)
        invoice,event,business,binding,local_data=prepare.capture(db,original,actor,executing=True)
        finished=facts.get(db,facts.FINISH,attempt.nonce,lock=True)
        facts.validate(db,attempt)
        if (event is None or event.action!='sync_done' or event.payload!=facts.event_payload(attempt)
                or finished is None or plans.digest(business)!=finished.result.get('after_binding_fingerprint')
                or plans.digest(event.result)!=finished.result.get('event_result_fingerprint')):
            prepare.reject(409,'已完成原单或当前验货绑定已变化，不能覆盖')
        chain=facts.chain(db,attempt)
        return invoice.id,deepcopy(finished.result['result']),binding,chain
    invoice_id,result,binding,chain=capture()
    baseline={item.nonce:facts.fingerprint(db,item) for item in chain}
    db.commit();clear(db)
    try:
        after=prepare.read_outbound(db,attempt.data['record']['outbound_invoice_id'])
        plans.verify(attempt.data['plan']['before'],after,attempt.data['plan'])
    except (ValueError,KeyError,TypeError,okki_client.OkkiApiError):
        prepare.reject(409,'迟到原事实与已完成出库资料不一致，请核对原单')
    finally:clear(db)
    _,_,latest,chain=capture()
    if latest!=binding or any(facts.fingerprint(db,item)!=baseline[item.nonce] for item in chain):
        prepare.reject(409,'原事实核对期间当前绑定或事实集合已变化')
    for item in chain:
        fingerprint=facts.fingerprint(db,item,include_reads=False)
        key=item.nonce+':'+fingerprint[:27]
        facts.append(db,facts.REVIEW,key,item,facts.identity(item),
            {'facts_fingerprint':fingerprint,'verified_fingerprint':plans.digest(after)})
    db.commit();clear(db)
    return response(db,record,user,invoice_id,warehouse,result)

def synchronize(db,record,user,version,*,check_only=False,confirm_recheck=False,desired_serial_id=None,
                number_only=False,repair=False,auto_recall=False,source='pc',warehouse=False):
    try:
        from app.shipping_inspection import outbound_sync_service as legacy
        # Read trusted prior requirements under current authority before any provider evidence.
        actor,original,_,prior,_,preflight_binding,_=local(db,record,user,warehouse)
        if prior is not None and (prior.payload or {}).get('protocol')==1:
            original_attempt=facts.load(db,prior)
            inherited=bool(warehouse or original_attempt.data['warehouse'])
            if inherited and not warehouse:
                try:
                    actor=employee_principal(db,actor['id'],'invoice:sync','shipping_inspection:write')
                except PortalError:
                    prepare.reject(403,'当前账号无权执行原仓库出库操作')
                actor={**actor,'sub':str(actor['id'])}
                prepare.mirror(db,original,actor,True)
            warehouse=inherited
        db.commit();clear(db)
        invoice,event,plan=prepare.prepare(db,record,user,desired_serial_id=desired_serial_id,
                                           number_only=number_only,warehouse=warehouse,expected_binding=preflight_binding)
        if plan is None:
            attempt=facts.load(db,event)
            warehouse=bool(warehouse or attempt.data['warehouse'])
            if event.action=='sync_done':
                db.commit();clear(db)
                return review_finished(db,record,user,warehouse,attempt)
            return recover(db,record,user,warehouse,event,attempt,repair=repair,check_only=check_only)
        if not plan['changed'] and event.action=='sync_done' and (event.payload or {}).get('protocol')==1:
            original=facts.load(db,event)
            warehouse=bool(warehouse or original.data['warehouse'])
            finished=facts.get(db,facts.FINISH,original.nonce)
            if finished is not None and isinstance(finished.result.get('result'),dict):
                result=deepcopy(finished.result['result']);invoice_id=invoice.id
                db.commit();clear(db)
                return response(db,record,user,invoice_id,warehouse,result)
        if check_only and plan['changed']:
            invoice_id=invoice.id;db.commit();clear(db)
            return response(db,record,user,invoice_id,warehouse,
                {'status':'sync_failed','requires_preview':True,'message':'原单仍有差异，请重新预览'})
        if not check_only and plan['version']!=version:prepare.reject(409,'订单或出库资料已变化，请重新预览')
        if plan['requires_recheck'] and not confirm_recheck:
            invoice_id=invoice.id;db.commit();clear(db)
            return response(db,record,user,invoice_id,warehouse,
                {'status':state.RECHECK,'message':'请由仓库确认同步并重验'})
        if plan['requires_recheck'] and plan['inspection']['status']=='submitted' and not auto_recall:
            prepare.reject(409,'验货单已提交，请先撤回再同步')
        permissions=('invoice:sync','shipping_inspection:write') if warehouse else ('invoice:sync',)
        actor=employee_principal(db,int(user.get('id') or user.get('sub') or 0),*permissions)
        actor={**actor,'sub':str(actor['id'])}
        original=prepare.mirror(db,record,actor,warehouse)
        _,_,business,binding,local_data=prepare.capture(db,original,actor,executing=True)
        if plans.digest(business)!=plan['local_binding_fingerprint']:prepare.reject(409,'原完整本地绑定已变化')
        if not plan['changed']:
            # Reuse verified local semantics; prepare already took exact outbound/order readbacks outside locks.
            event.payload={'invoice_id':invoice.id,'plan':plan};event.source=source
            result=legacy._finish_verified(db,event,plan,plan['before'],commit_result=False,finisher_id=actor['id'])
            invoice_id=invoice.id;db.commit();clear(db)
            return response(db,record,user,invoice_id,warehouse,result)
        db.commit();clear(db)
        access_token=token(db)
        attempt=claim(db,record,user,warehouse,plan,binding,auto_recall,source)
        return send_attempt(db,record,user,warehouse,attempt,access_token,local_data)
    except HTTPException as error:
        clear(db);prepare.reject(error.status_code,error.detail)
    except (ValueError,KeyError,TypeError) as error:
        trace=error.__traceback__
        while trace.tb_next:trace=trace.tb_next
        origin=trace.tb_frame.f_code.co_name
        logger.warning('Outbound binding invalid kind=%s origin=%s',type(error).__name__,origin)
        print('[outbound-execution] binding invalid '+type(error).__name__+' '+origin,flush=True)
        clear(db);prepare.reject(409,'原出库执行身份或绑定无效，请核对原任务')
    except SQLAlchemyError:
        clear(db);unavailable()
