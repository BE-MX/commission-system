from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
import publish


def test_windows_sharing_violation_retries_only_rename(tmp_path, monkeypatch):
    path=tmp_path/'journal.json';path.write_text('old')
    replace=publish.os.replace
    error=PermissionError('sharing');error.winerror=32
    calls=[]
    def rename(source,dest):
        calls.append((source,dest))
        if len(calls)<3:raise error
        replace(source,dest)
    monkeypatch.setattr(publish.os,'replace',rename)
    monkeypatch.setattr(publish.time,'sleep',Mock())
    publish.atomic_json(path,{'status':'succeeded'})
    assert len(calls)==3 and len(set(calls))==1
    assert 'succeeded' in path.read_text()
    assert not path.with_suffix('.next').exists()


@pytest.mark.parametrize('windows', [False,True])
def test_persistent_denial_is_bounded_and_preserves_original(tmp_path,monkeypatch,windows):
    path=tmp_path/'journal.json';path.write_text('old')
    error=PermissionError('denied')
    if windows:error.winerror=5
    rename=Mock(side_effect=error)
    monkeypatch.setattr(publish.os,'replace',rename)
    monkeypatch.setattr(publish.time,'sleep',Mock())
    with pytest.raises(PermissionError):publish.atomic_json(path,{'new':True})
    assert rename.call_count==(10 if windows else 1)
    assert path.read_text()=='old'
    assert path.with_suffix('.next').exists()
