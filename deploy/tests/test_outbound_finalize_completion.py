"""Actual historical finalizer execute bodies with all external effects replaced."""
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_pipeline_contract import pipeline  # noqa: F401
import publish
import schema_release as schema
import office_release
import static_sync
import colorwork_routing
import okki_outbound_release as release


@pytest.fixture(params=['release_finalize','recover_colorwork_order_office'])
def finalizer(request,pipeline,monkeypatch):
    entry=importlib.import_module(request.param)
    root=publish.ROOT
    revision=entry.REVISION if request.param.startswith('recover') else 'a'*40
    target=entry.SCHEMA if request.param.startswith('recover') else '159_storage_transfers'
    candidate=root/'.deploy_state/sources'/revision;candidate.mkdir(parents=True)
    ssh=root/'owned-git/usr/bin/ssh.exe';ssh.parent.mkdir(parents=True);ssh.touch()
    monkeypatch.setattr(entry,'Path',lambda value:root if str(value)=='D:/commission-system' else Path(value))
    monkeypatch.setattr(entry.shutil,'which',lambda name:str(root/'owned-git/bin/git.exe') if name=='git' else 'owned-nssm')
    monkeypatch.setenv('PATH',os.environ.get('PATH',''))
    monkeypatch.setenv('PYTHONUTF8',os.environ.get('PYTHONUTF8','0'))
    def run(command,**_):
        if any('rev-parse' in str(part) for part in command):return revision
        if command[1:3]==['get','CommissionSystem']:return 'python.exe'
        return ''
    monkeypatch.setattr(publish,'run',run)
    monkeypatch.setattr(entry.subprocess,'run',Mock(side_effect=AssertionError('External process forbidden')))
    monkeypatch.setattr(schema,'validate',lambda *_:[])
    checked={'schema':target,'database':target,'pending':[]}
    monkeypatch.setattr(schema,'schema_check',Mock(return_value=checked))
    monkeypatch.setattr(office_release,'health',Mock())
    monkeypatch.setattr(static_sync,'remote_python',Mock(return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')))
    monkeypatch.setattr(colorwork_routing,'activate',Mock(side_effect=lambda item,*_: {'region':item['payload']['region']}))
    monkeypatch.setattr(release,'artifact',Mock(return_value={}))
    pipeline.outbound_prepare(root,revision,'c'*32)
    journal={'status':'failed','revision':revision,'release_id':'c'*32,
             'completed':['office'] if request.param.startswith('recover') else ['office','beijing-backend'],
             'outbound':pipeline.receipt('activate')}
    migration={'status':'upgraded','schema':target,'pending':[target],
               'database':'159_storage_transfers','writers':[],'stopped':[]}
    publish.atomic_json(pipeline.state/'publish-current.json',journal)
    publish.atomic_json(pipeline.state/'schema-writers.json',migration)
    publish.atomic_json(pipeline.state/'office-success.json',{'revision':revision,'schema':target})
    return entry,pipeline,revision,journal


@pytest.mark.parametrize('prepare_only',[True,False])
def test_both_finalizers_use_actual_shared_guard_before_success(finalizer,prepare_only):
    entry,pipeline,revision,_=finalizer
    result=entry.execute({'revision':revision,'prepare_only':prepare_only})
    assert result['status']==('prepared' if prepare_only else 'succeeded')
    assert pipeline.outbound_phase.call_count==(1 if prepare_only else 2)
    if prepare_only:
        pipeline.activate.assert_not_called()
        assert not (pipeline.state/'publish-success.json').exists()
    else:
        summary=json.loads((pipeline.state/'publish-success.json').read_text())
        assert summary['outbound']['status']=='verified' and summary['outbound']['release_confirmed'] is True


@pytest.mark.parametrize('fault',['missing','bad_release'])
def test_both_finalizers_reject_historical_bad_receipt_before_effects(finalizer,fault):
    entry,pipeline,revision,journal=finalizer
    if fault=='missing':del journal['outbound']
    else:journal['outbound']['release_confirmed']=False
    publish.atomic_json(pipeline.state/'publish-current.json',journal)
    with pytest.raises(RuntimeError,match='receipt'):
        entry.execute({'revision':revision})
    pipeline.activate.assert_not_called();pipeline.outbound_phase.assert_not_called()
    release.pause_registered.assert_called_once_with()
    assert not (pipeline.state/'publish-success.json').exists()


def test_both_finalizers_recheck_after_static_effects_before_success(finalizer):
    entry,pipeline,revision,_=finalizer;calls=[]
    def phase(_,action):
        calls.append(action);receipt=pipeline.receipt(action)
        if len(calls)==2:receipt['database_fingerprint']='f'*64
        return receipt
    pipeline.outbound_phase.side_effect=phase
    with pytest.raises(RuntimeError,match='receipt'):
        entry.execute({'revision':revision})
    assert calls==['verify','verify']
    pipeline.activate.assert_called_once()
    release.pause_registered.assert_called_once_with()
    assert not (pipeline.state/'publish-success.json').exists()
    assert json.loads((pipeline.state/'schema-writers.json').read_text())['status']=='upgraded'
