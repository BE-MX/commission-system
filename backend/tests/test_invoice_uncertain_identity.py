"""Remote identity proof must reject aliases before any business write."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.invoice.uncertain_recovery import verify_existing


def evidence_case():
    rows=[dict(product_id=1,sku_id=11,count=1,unit_price=10,cost_amount=10),
          dict(product_id=2,sku_id=22,count=1,unit_price=20,cost_amount=20)]
    invoice=SimpleNamespace(xiaoman_order_id=401,customer_id=7,currency='USD',
                            total_amount=Decimal('30'),surcharge_amount=Decimal('0'))
    evidence=dict(order_id=401,company_id=7,currency='USD',amount=30,
                  product_list=[dict(rows[0],unique_id='501'),dict(rows[1],unique_id='502')])
    return invoice,rows,evidence


@pytest.mark.parametrize('uid',['0501','501',501,True,False,0,-1,'0','-1','+502',' 502','502 ',
                                '1e2','502.0',502.0,'١٢','²',None,'', '9'*65])
def test_invalid_or_duplicate_unanchored_remote_identity_is_rejected_without_mutation(uid):
    invoice,rows,data=evidence_case();data['product_list'][1]['unique_id']=uid
    before=deepcopy((rows,data))
    with pytest.raises(ValueError):verify_existing(invoice,rows,data)
    assert (rows,data)==before


@pytest.mark.parametrize('uids',[(501,502),('501','502'),(501,'502')])
def test_distinct_canonical_identities_match_and_remain_read_only(uids):
    invoice,rows,data=evidence_case()
    for row,uid in zip(data['product_list'],uids):row['unique_id']=uid
    before=deepcopy((rows,data))
    normalized=verify_existing(invoice,rows,data)
    assert [r['unique_id'] for r in normalized]==['501','502']
    assert (rows,data)==before


def test_anchored_identity_cannot_be_reassigned_by_matching_commercial_signature():
    invoice,rows,data=evidence_case();rows[0]['unique_id']=501
    data['product_list'][0]['unique_id']=900
    with pytest.raises(ValueError):verify_existing(invoice,rows,data)
