import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('release_finalize',
    Path(__file__).resolve().parents[1] / 'release_finalize.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def data():
    return [{'status':'failed','revision':'a'*40,'completed':['office','beijing-backend']},
            {'status':'upgraded','schema':'159_storage_transfers'},
            {'revision':'a'*40,'schema':'159_storage_transfers'}, 'a'*40, 'a'*40, 'a'*40]


def test_only_exact_successfully_activated_release_can_finalize():
    module.validate(*data())


@pytest.mark.parametrize('index,key,value', [
    (0,'status','succeeded'), (0,'completed',['office']), (0,'revision','b'*40),
    (1,'status','failed-after-ddl'), (1,'schema','158_invoice_linked_sync'),
    (2,'revision','b'*40), (2,'schema','158_invoice_linked_sync'),
])
def test_rejects_unverified_backend_or_schema_state(index,key,value):
    args=data();args[index][key]=value
    with pytest.raises(RuntimeError):module.validate(*args)


@pytest.mark.parametrize('index', [4,5])
def test_rejects_live_revision_drift(index):
    args=data();args[index]='b'*40
    with pytest.raises(RuntimeError):module.validate(*args)


@pytest.mark.parametrize('dirty', [(' M frontend/src/main.js',''), ('','M  backend/app/main.py')])
def test_rejects_unreviewed_tracked_runtime_changes(dirty):
    with pytest.raises(RuntimeError, match='Tracked runtime'):
        module.validate(*data(), *dirty)
