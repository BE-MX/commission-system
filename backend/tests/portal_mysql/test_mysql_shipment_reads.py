"""Current shipment quote/reads with actual main/JWT/admin/owned MySQL."""
from copy import deepcopy
from uuid import uuid4
import pytest
from test_mysql_shipment_create import (shipment_app, body_for, path, snapshot, authorize,
    login, change_user, created)  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


ROUTES=('quote','capabilities','order','detail')


def setup(client,c,route):
    root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
    if route not in {'quote','capabilities'}:
        body=body_for(client,c,owner,payment=False)
        c.settlement_id=created(c,body,client.post(path(c),headers=owner,json=body))
    return root,owner


def request(client,c,route,owner):
    if route=='quote':
        return client.post(f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=owner,
            json={'items':[{'invoice_item_id':c.item_id,'quantity':4}],'freight_amount':'20.00'})
    address={'capabilities':'/api/shipments/capabilities','order':f'/api/shipments/order/{c.invoice_id}',
        'detail':f'/api/shipments/{getattr(c,"settlement_id",0)}'}[route]
    return client.get(address,headers=owner)


@pytest.mark.parametrize('route',ROUTES)
@pytest.mark.parametrize('revoke',['disabled','roles','actions'])
def test_current_revocation_before_read_denies_no_write(shipment_app,route,revoke):
    c=shipment_app
    with c.app.client() as client:
        root,owner=setup(client,c,route)
        baseline=request(client,c,route,owner);assert baseline.status_code==200,baseline.text
        if revoke=='disabled':change_user(client,c,root,{'is_active':False})
        elif revoke=='roles':change_user(client,c,root,{'role_ids':[]})
        else:
            roles={'quote':[c.roles['shipment:write'],c.roles['write']],
                'capabilities':[c.roles['shipment:write']],
                'order':[c.roles['invoice:write'],c.roles['write']],
                'detail':[c.roles['invoice:write'],c.roles['write']]}[route]
            change_user(client,c,root,{'role_ids':roles})
        before=snapshot(c);c.io.clear()
        response=request(client,c,route,owner)
        assert response.status_code==403 and response.headers.get('cache-control')=='private, no-store',response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('route',ROUTES)
def test_current_grant_applies_to_old_token(shipment_app,route):
    c=shipment_app
    with c.app.client() as client:
        root,_=setup(client,c,route);change_user(client,c,root,{'role_ids':[]});owner=login(client,c,c.owner_name)
        authorize(client,c,root);before=snapshot(c);c.io.clear()
        response=request(client,c,route,owner)
        assert response.status_code==200 and response.headers.get('cache-control')=='private, no-store',response.text
        assert snapshot(c)==before and c.calls==[]
        if route=='quote':assert response.json()['data']['new_payment_due']=='64.00' and c.io
        else:assert c.io==[]
