"""Deferred cleanup receipts must remain bound to the verified publication."""
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import maintenance_status as maintenance


def setup_state(tmp_path):
    current = dict(status='succeeded', revision='a' * 40, release_id='release')
    pending = dict(current, status='pending', static_retention={'status': 'deferred'},
                   candidate_retention={'status': 'deferred'})
    (tmp_path / 'publish-current.json').write_text(json.dumps(current))
    (tmp_path / 'maintenance-pending.json').write_text(json.dumps(pending))
    return pending


def test_each_success_closes_only_its_component(tmp_path):
    setup_state(tmp_path)
    maintenance.complete(tmp_path, 'static_retention', {'status': 'succeeded'})
    assert json.loads((tmp_path / 'maintenance-pending.json').read_text())['status'] == 'pending'
    maintenance.complete(tmp_path, 'candidate_retention', {'status': 'succeeded'})
    assert json.loads((tmp_path / 'maintenance-pending.json').read_text())['status'] == 'succeeded'


@pytest.mark.parametrize('status', ['prepared', 'failed'])
def test_incomplete_cleanup_does_not_close_pending(tmp_path, status):
    before = setup_state(tmp_path)
    maintenance.complete(tmp_path, 'static_retention', {'status': status})
    assert json.loads((tmp_path / 'maintenance-pending.json').read_text()) == before


@pytest.mark.parametrize('field', ['revision', 'release_id', 'status'])
def test_drift_never_closes_another_release(tmp_path, field):
    before = setup_state(tmp_path)
    path = tmp_path / 'publish-current.json'
    current = json.loads(path.read_text()); current[field] = 'changed'
    path.write_text(json.dumps(current))
    with pytest.raises(RuntimeError, match='current publication'):
        maintenance.complete(tmp_path, 'static_retention', {'status': 'succeeded'})
    assert json.loads((tmp_path / 'maintenance-pending.json').read_text()) == before
