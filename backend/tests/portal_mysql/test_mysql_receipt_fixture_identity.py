"""The synthetic upstream keeps the real globally unique receipt mapping."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.receipt.models import Receipt
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, _has_unique_remote_mapping  # noqa: F401


def test_remote_identity_constraint_exists_before_reconciliation(receipt_app):
    c=receipt_app
    with c.ctx.engine.connect() as connection:
        indexes=connection.execute(text('SHOW INDEX FROM ark_receipts')).mappings().all()
        assert _has_unique_remote_mapping(indexes)
    with Session(c.ctx.engine) as db:
        own=db.get(Receipt,c.receipts['victim'])
        foreign=db.get(Receipt,c.receipts['foreign'])
        remote_id=str(500000000+own.id)
        own.xiaoman_receipt_id=remote_id
        db.commit()
        foreign.xiaoman_receipt_id=remote_id
        with pytest.raises(IntegrityError) as caught:
            db.commit()
        assert caught.value.orig.args[0]==1062
        db.rollback()
    with Session(c.ctx.engine) as db:
        assert db.get(Receipt,c.receipts['victim']).xiaoman_receipt_id==remote_id
        assert db.get(Receipt,c.receipts['foreign']).xiaoman_receipt_id is None
        assert list(db.scalars(select(Receipt.id).where(Receipt.xiaoman_receipt_id==remote_id)))==[c.receipts['victim']]


@pytest.mark.parametrize('columns,non_unique,prefix,expected',[
    (['xiaoman_receipt_id'],0,None,True),
    (['invoice_id','xiaoman_receipt_id'],0,None,False),
    (['xiaoman_receipt_id','invoice_id'],0,None,False),
    (['xiaoman_receipt_id'],0,8,False),
    (['xiaoman_receipt_id'],1,None,False),
    (['invoice_id'],0,None,False),
])
def test_only_full_single_column_remote_mapping_is_global(columns,non_unique,prefix,expected):
    rows=[{'Key_name':'test_index','Column_name':column,'Seq_in_index':position,
        'Non_unique':non_unique,'Sub_part':prefix} for position,column in enumerate(columns,1)]
    assert _has_unique_remote_mapping(rows) is expected


def test_distinct_indexes_do_not_form_one_composite_mapping():
    rows=[{'Key_name':'invoice','Column_name':'invoice_id','Seq_in_index':1,'Non_unique':0,'Sub_part':None},
        {'Key_name':'receipt','Column_name':'xiaoman_receipt_id','Seq_in_index':1,'Non_unique':0,'Sub_part':None}]
    assert _has_unique_remote_mapping(rows)
