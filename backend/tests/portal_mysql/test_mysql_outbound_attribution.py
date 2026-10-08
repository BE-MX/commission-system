"""Actual warehouse employee scope and separately attributed original/finishing actors."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import utils
from app.auth.models import ArkUser,ArkPermission,ArkRole,ArkRolePermission,ArkUserRole
from app.portal.authority import lock_authority
from app.core.time import beijing_now
from app.shipping_inspection import outbound_sync_service as sync,outbound_facts as facts
from app.shipping_inspection.models import ShippingInspection,ShippingInspectionPhoto,ShippingOperationEvent
from test_mysql_outbound_prepare import setup,preview
from test_mysql_outbound_execution import install_post,rows


def test_actual_nonadmin_warehouse_employee_uses_bound_scope_and_named_original_actor(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);password='owned-test-'+uuid4().hex
    with Session(editor.ctx.engine) as db:
        lock_authority(db,force=True)
        actor=db.get(ArkUser,editor.ctx.actor);actor.real_name='Owned warehouse operator';actor.password_hash=utils.hash_password(password)
        username=actor.username
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='shipping_inspection:write'))
        if permission is None:
            permission=ArkPermission(code='shipping_inspection:write',module='shipping_inspection',action='write',label='Owned write',kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='owned-warehouse-'+uuid4().hex[:8],label='Owned warehouse role');db.add(role);db.flush()
        db.add_all([ArkUserRole(user_id=actor.id,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=permission.id)]);db.commit()
    async def login():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=editor.app),base_url='https://ark.example.test') as client:
            response=await client.post('/api/auth/login',json={'username':username,'password':password});assert response.status_code==200
            return response.json()['access_token']
    token=asyncio.run(login());install_post(c,monkeypatch)
    first=asyncio.run(editor.write(c.route,{},'POST',token));assert first.status_code==200,first.text
    result=asyncio.run(editor.write(c.route.removesuffix('/preview'),{'expected_version':first.json()['data']['version']},'POST',token))
    assert result.status_code==200 and result.json()['data']['status']=='sync_done',result.text
    assert len(c.posts)==1
    with Session(editor.ctx.engine) as db:
        row=db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope=='outbound-invoice-sync',ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']))
        assert row.operator_user_id==editor.ctx.actor and row.operator_name=='Owned warehouse operator'
        original=facts.get(db,facts.START,row.payload['send_nonce'])
        assert original.operator_user_id==editor.ctx.actor and original.operator_name==row.operator_name


@pytest.mark.parametrize('initial_status',['submitted','draft'])
def test_new_current_actor_recovers_inactive_sender_with_separate_recall_attribution(editor,monkeypatch,tmp_path,initial_status):
    c=setup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection=ShippingInspection(outbound_record_id=c.record['outbound_record_id'],outbound_no='CK-OWN',status=initial_status,updated_by=editor.ctx.admin)
        db.add(inspection);db.flush();db.add(ShippingInspectionPhoto(inspection_id=inspection.id,file_path='owned.png'));db.commit()
    first=preview(c);assert first.status_code==200
    def revoke():
        with Session(editor.ctx.engine) as db:
            lock_authority(db,force=True);db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
    install_post(c,monkeypatch,revoke)
    with Session(editor.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:
            sync.synchronize(db,c.record,{'sub':str(editor.ctx.admin)},first.json()['data']['version'],
                force_authority=True,confirm_recheck=True,auto_recall=True,source='invoice_sync')
        assert error.value.status_code==403
    original=rows(c,facts.START)[0];assert original[1]['actor_id']==editor.ctx.admin
    monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    with Session(editor.ctx.engine) as db:
        result=sync.synchronize(db,c.record,{'sub':str(editor.ctx.actor)},None,check_only=True,force_authority=True)
        assert result['status']=='sync_done'
    assert len(c.posts)==1 and rows(c,facts.START)==[original]
    with Session(editor.ctx.engine) as db:
        inspection=db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id==c.record['outbound_record_id']))
        assert inspection.status=='draft' and inspection.edit_version==1
        assert inspection.updated_by==editor.ctx.actor
        recall=db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.action=='recall',ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']))
        if initial_status=='submitted':
            assert inspection.recalled_by==editor.ctx.actor and recall.operator_user_id==editor.ctx.actor
        else:
            assert inspection.recalled_by is None and recall is None
    assert rows(c,facts.FINISH)[0][2]['finished_by']==editor.ctx.actor
