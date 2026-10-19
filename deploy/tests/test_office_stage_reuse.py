from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import office_release as office


def test_prepared_static_reuses_exact_candidate_but_rechecks_live_and_staged_bytes(tmp_path, monkeypatch):
    live, source, state = tmp_path / 'live', tmp_path / 'build', tmp_path / 'state'
    destination = live / 'frontend/dist'
    destination.mkdir(parents=True); source.mkdir(); state.mkdir()
    (destination / 'index.html').write_text('old')
    (source / 'index.html').write_text('new')
    monkeypatch.setattr(office, 'STATE', state)
    monkeypatch.setattr(office, 'marker', lambda *_: {})
    prepared = dict(live=live, revision='a' * 40)
    office.stage_static({'frontend': source}, prepared)
    staged = prepared['static'][0][2]
    copy = Mock(wraps=office.shutil.copytree)
    monkeypatch.setattr(office.shutil, 'copytree', copy)
    office.stage_static({'frontend': source}, prepared)
    assert prepared['static'][0][2] == staged
    copy.assert_not_called()
    (staged / 'index.html').write_text('corrupt')
    with pytest.raises(RuntimeError, match='staged'):
        office.stage_static({'frontend': source}, prepared)
    (staged / 'index.html').write_text('new')
    (destination / 'index.html').write_text('another release')
    office.stage_static({'frontend': source}, prepared)
    assert prepared['static'][0][2] != staged
