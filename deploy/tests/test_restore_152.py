import copy
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from restore_152 import validate_schema, validate_journal
import restore_152


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


@pytest.mark.parametrize('change', [
    {'host': 'ubuntu@154.8.205.162'},
    {'host': 'root@203.0.113.10'},
    {'executable': '/root/.nvm/versions/node/v99.0.0/bin/pm2'},
    {'service': 'unrelated-worker'},
])
def test_historical_writer_identity_is_exact_even_if_stopped_matches(change):
    record = journal()
    record['writers'][3]['writer'].update(change)
    record['stopped'][3].update(change)
    with pytest.raises(RuntimeError, match='Writer evidence differs'):
        validate_journal(record)


def test_duplicate_historical_writer_cannot_replace_another():
    record = journal()
    record['writers'][3] = copy.deepcopy(record['writers'][0])
    record['stopped'][3] = copy.deepcopy(record['stopped'][0])
    with pytest.raises(RuntimeError, match='Writer evidence differs'):
        validate_journal(record)


def test_evidence_validation_is_independent_of_current_schema_validator(monkeypatch):
    current_validator = Mock(side_effect=AssertionError('Current topology must not validate old evidence'))
    monkeypatch.setattr(restore_152.schema_release, 'validate', current_validator)
    assert validate_journal(journal()) == journal()['stopped']
    current_validator.assert_not_called()


def test_identical_verified_topology_is_accepted():
    writers = validate_journal(journal())
    restore_152.validate_current_topology(writers, {
        'migration_writers_verified': True, 'migration_writers': list(reversed(writers)),
    })


@pytest.mark.parametrize('change', ['moved', 'added', 'removed', 'unverified', 'duplicate'])
def test_changed_current_topology_cannot_authorize_historical_recovery(change):
    writers = validate_journal(journal())
    inventory = {'migration_writers_verified': True, 'migration_writers': copy.deepcopy(writers)}
    if change == 'moved':
        inventory['migration_writers'][3]['host'] = 'ubuntu@154.8.205.162'
    elif change == 'added':
        inventory['migration_writers'].append({'kind': 'systemd_timer', 'host': 'ubuntu@154.8.205.162',
                                              'service': 'ark-okki-outbound-poller'})
    elif change == 'removed':
        inventory['migration_writers'].pop()
    elif change == 'duplicate':
        inventory['migration_writers'][3] = copy.deepcopy(writers[0])
    else:
        inventory['migration_writers_verified'] = False
    with pytest.raises(RuntimeError, match='topology has changed'):
        restore_152.validate_current_topology(writers, inventory)


def test_current_migrated_inventory_blocks_legacy_execute_before_external_actions(monkeypatch):
    if restore_152.os.name != 'nt':
        pytest.skip('Recovery entry is restricted to the installed Windows server')
    external = Mock(side_effect=AssertionError('No installed service may be contacted'))
    control = Mock(side_effect=AssertionError('No historical process may be started'))
    monkeypatch.setattr(restore_152.subprocess, 'check_output', external)
    monkeypatch.setattr(restore_152.schema_release, 'control', control)
    with pytest.raises(RuntimeError, match='topology has changed'):
        restore_152.execute('unused-plan.json')
    external.assert_not_called()
    control.assert_not_called()
