import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from restore_152 import validate_schema, validate_journal


def snapshot():
    return {"revision":["152_shipping_media_recall"], "future_tables":[], "customer_seed":0,
            "tag_scope":{"length":16,"nullable":False,"default":"internal"},
            "index":{"columns":["tag_scope"],"unique":False}, "unsigned_ids":[True,True,False]}


def journal():
    writers=[{"kind":"nssm","host":"office","service":"CommissionSystem"},
             {"kind":"nssm","host":"office","service":"WhatsAppConnector"},
             {"kind":"systemd","host":"ubuntu@154.8.205.162","service":"ark-backend"},
             {"kind":"pm2","host":"root@119.28.107.92","service":"shipment-tracking-mcp",
              "executable":"/root/.nvm/versions/node/v22.22.1/bin/pm2"}]
    return {"status":"failed-after-ddl","database":"152_shipping_media_recall",
            "schema":"154_okki_outbound_tasks", "pending":["151_customer_media_tags","153_shipping_station","154_okki_outbound_tasks"],
            "stopped":copy.deepcopy(writers),"writers":[{"writer":w,"before":"running"} for w in writers]}


def test_reviewed_additive_state_is_accepted():
    validate_schema(snapshot())
    assert len(validate_journal(journal())) == 4


@pytest.mark.parametrize('key,value', [
    ('revision',['151_customer_media_tags']), ('future_tables',['ark_customer_media_asset_tags']),
    ('customer_seed',1), ('tag_scope',{'length':16,'nullable':False,'default':'customer'}),
    ('index',{'columns':['tag_scope'],'unique':True}), ('unsigned_ids',[False,False,False]),
])
def test_unreviewed_database_state_blocks(key,value):
    value_map=snapshot();value_map[key]=value
    with pytest.raises(RuntimeError): validate_schema(value_map)


@pytest.mark.parametrize('key,value', [('status','upgraded'),('database','151_customer_media_tags'),
    ('pending',[]),('schema','other'),('writers',[]),('stopped',[])])
def test_wrong_incident_or_incomplete_baseline_blocks(key,value):
    record=journal();record[key]=value
    with pytest.raises(RuntimeError): validate_journal(record)


def test_changed_original_writer_state_blocks():
    record=journal();record['writers'][0]['before']='stopped'
    with pytest.raises(RuntimeError): validate_journal(record)


def test_only_observed_beijing_runtime_files_are_allowed():
    from restore_152 import validate_beijing_untracked
    validate_beijing_untracked(['backend/.env.bak-20260731', 'backend/D:/WORKSOURCE/domestic/example.jpg', ''])
    with pytest.raises(RuntimeError):
        validate_beijing_untracked(['backend/app/unknown.py'])
