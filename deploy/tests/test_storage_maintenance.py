"""Maintenance gates must survive a release and preserve unrelated route edits."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('storage_maintenance_remote',
    Path(__file__).resolve().parents[1] / 'storage_maintenance_remote.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('count', [1, 2])
def test_freeze_and_restore_preserve_routes_added_during_release(count):
    original = 'server {\n    location /api/ { proxy_pass http://127.0.0.1:8001; }\n}\n' * count
    frozen = module.render(original, count)
    assert frozen.count(module.GATE) == count
    added = '\n# a reviewed storage routing change\n'
    assert module.render(frozen + added, count, True) == original + added


def test_refuses_repeated_freeze_and_missing_or_changed_restore_gate():
    source = 'server {\nlocation /api/ { }\n}'
    frozen = module.render(source, 1)
    with pytest.raises(RuntimeError):
        module.render(frozen, 1)
    with pytest.raises(RuntimeError):
        module.render(source, 1, True)
    with pytest.raises(RuntimeError):
        module.render(frozen.replace('503', '404'), 1, True)


def test_mismatched_server_layout_is_not_silently_partially_frozen():
    source = 'server {\nlocation /api/ { }\n}'
    with pytest.raises(RuntimeError):
        module.render(source, 2)


def test_caret_api_location_is_supported():
    source = 'server {\n  location ^~ /api/ { }\n}'
    frozen = module.render(source, 1)
    assert module.render(frozen, 1, True) == source


def test_independent_media_domain_is_frozen():
    source = 'server {\n location ^~ /api/customer-media/ { }\n}'
    frozen = module.render(source, 1, api_prefix='/api/customer-media/')
    assert module.GATE in frozen
    assert module.render(frozen, 1, True) == source
    assert any('customer-media.leshine.cloud.conf' in path for path, _ in module.SPECS['beijing'])


def test_office_stop_failure_recovers_changed_service_and_own_rule(tmp_path, monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location('maintenance_office',
        Path(__file__).resolve().parents[1] / 'storage_maintenance_office.py')
    office = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(office)
    monkeypatch.setattr(office, 'STATE', tmp_path)
    monkeypatch.setattr(office.shutil, 'which', lambda _: 'nssm')
    live = {'service': 'SERVICE_RUNNING', 'rule': False}
    def run(args):
        if args[1] == 'status':
            return live['service']
        if args[1] == 'stop':
            live['service'] = 'SERVICE_STOPPED'
            raise RuntimeError('stop changed state then failed')
        if args[1] == 'start':
            live['service'] = 'SERVICE_RUNNING'
            return ''
        raise AssertionError(args)
    def ps(code):
        if code.startswith('New-NetFirewallRule'):
            live['rule'] = True
        elif code.startswith('Remove-NetFirewallRule'):
            live['rule'] = False
        else:
            raise AssertionError(code)
        return ''
    monkeypatch.setattr(office, 'run', run)
    monkeypatch.setattr(office, 'ps', ps)
    monkeypatch.setattr(office, 'check_rule', lambda: live['rule'])
    with pytest.raises(RuntimeError, match='stop changed'):
        office.execute({'action': 'freeze', 'attempt': 'test'})
    assert live == {'service': 'SERVICE_RUNNING', 'rule': False}
    assert json.loads((tmp_path / 'test/office.json').read_text())['status'] == 'restored'
