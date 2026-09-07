"""Editable prompts: permissions, atomic capture, immutable jobs and seed parity."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.expo import ai_pipeline, prompt_service, router as router_module, service
from app.expo.models import ExpoPromptVersion, ExpoResult
from app.expo.prompt_renderer import render_prompt
from app.expo.prompt_schemas import PromptConfig, PromptVersionUpdate
from app.expo.schemas import GenerateRequest
from tests.expo_prompt_support import SEEDS, config, seed_versions
from tests.test_expo_generate_quota import _client, _make_session, _make_store, _make_wig

GOLDEN = json.loads((Path(__file__).parent / 'fixtures/expo_legacy_prompt_hashes.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', GOLDEN)
def test_all_initial_prompts_equal_rolled_back_production(case, monkeypatch):
    monkeypatch.setattr('app.expo.prompt_renderer.random.choice', lambda values: values[0])
    session = SimpleNamespace(photo_path='golden.jpg')
    row = SimpleNamespace(wig_id=1 if case['mode'] == 'tryon' else None,
                          scene_json={'key': case['scene_key']} if case['scene_key'] else None,
                          hair_color_json=None)
    wig = SimpleNamespace(name='Golden wig', wig_description='short bob', composite_prompt='', angle_photos=[], cover_path=None)
    text, images, size = render_prompt(session, row, wig, SEEDS[case['version_id'] - 1]['config_json'], ai_pipeline.to_abs)
    assert hashlib.sha256(text.encode()).hexdigest() == case['sha256']
    assert size == case['size']
    assert len(images) == 1


@pytest.mark.parametrize('template', ['{unknown}', '{description.__class__}', '{description!r}', '{description:>5}', '{', '{}'])
def test_unsafe_or_unknown_placeholders_rejected(template):
    value = config(); value['parts']['tryon_base'] = template
    with pytest.raises(ValidationError):
        PromptConfig.model_validate(value)


def test_empty_optional_parts_are_respected_and_no_fixed_enum():
    value = config(); value['parts']['finish'] = ''
    assert PromptConfig.model_validate(value).parts['finish'] == ''
    value['parts']['tryon_base'] = ' '
    with pytest.raises(ValidationError): PromptConfig.model_validate(value)
    assert GenerateRequest(prompt_version_id=932).prompt_version_id == 932
    with pytest.raises(ValidationError): GenerateRequest(prompt_variant='real')


def test_crud_revision_default_and_admin_permissions(db):
    seed_versions(db)
    with _client(db, permissions=('expo:admin',)) as (client, user):
        response = client.post('/api/expo/prompt-versions', json={'name': '自定义 A', 'config': config()})
        assert response.status_code == 200
        row = response.json()['data']; version_id = row['id']
        assert row['revision'] == 1 and row['name'] == '自定义 A'
        body = {'name': '自定义 A', 'hint': '柔和处理', 'is_active': True, 'config': config(), 'expected_revision': 1}
        body['config']['parts']['finish'] = 'CUSTOM CONTENT.'
        assert client.put(f'/api/expo/prompt-versions/{version_id}', json=body).json()['data']['revision'] == 2
        assert client.put(f'/api/expo/prompt-versions/{version_id}', json=body).status_code == 409
        assert client.post(f'/api/expo/prompt-versions/{version_id}/default', json={'expected_revision': 2}).status_code == 200
        body.update(expected_revision=3, is_active=False)
        assert client.put(f'/api/expo/prompt-versions/{version_id}', json=body).status_code == 400
        assert db.query(ExpoPromptVersion).filter_by(default_slot=1).one().id == version_id
        assert db.get(ExpoPromptVersion, version_id).updated_by == user.id
        preview = client.post('/api/expo/prompt-versions/preview', json={'config': body['config']})
        assert preview.status_code == 200
        assert 'CUSTOM CONTENT.' in preview.json()['data']['prompt']
        assert db.query(ExpoResult).count() == 0
    # Reuse the same user with a kiosk token (helper creates a distinct user).
    user.username = 'previous'; db.commit()
    with _client(db) as (client, _):
        picker = client.get('/api/expo/prompt-versions/picker').json()['data']
        assert picker[0]['id'] == version_id
        assert all('config' not in row for row in picker)
        for method, url, body in [('get', '/prompt-versions', None), ('get', f'/prompt-versions/{version_id}', None),
                                 ('post', '/prompt-versions/preview', {'config': config()}),
                                 ('post', '/prompt-versions', {'name': '无权限', 'config': config()}),
                                 ('put', f'/prompt-versions/{version_id}', {'name': '无权限', 'config': config(), 'expected_revision': 3}),
                                 ('post', f'/prompt-versions/{version_id}/default', {'expected_revision': 3}),
                                 ('get', '/results/1/prompt-snapshot', None)]:
            assert client.request(method, '/api/expo' + url, json=body).status_code == 403


@pytest.mark.parametrize('mode', ['tryon', 'scene'])
def test_generation_uses_latest_config_and_snapshots_every_row(db, monkeypatch, mode):
    seed_versions(db)
    monkeypatch.setattr(router_module, 'launch_composite_threads', lambda *args: None)
    with _client(db) as (client, _user):
        store = _make_store(db, _user.id)
        session = _make_session(db, mode=mode)
        wig = _make_wig(db)
        version = db.get(ExpoPromptVersion, 2)
        changed = config('soft'); changed['parts']['finish'] = 'LATEST EDIT.'
        prompt_service.update_version(db, 2, PromptVersionUpdate(name=version.name, hint=version.hint,
            config=changed, expected_revision=1), None)
        db.commit()
        payload = {'prompt_version_id': 2, 'wig_ids': [wig.id, wig.id], 'scene_keys': ['cafe', 'home']}
        response = client.post(f'/api/expo/sessions/{session.id}/generate', json=payload)
        assert response.status_code == 200, response.text
        rows = db.query(ExpoResult).all()
        assert len(rows) == 2 and store.used_quota == 2
        assert all(r.prompt_version_id == 2 and r.prompt_snapshot['revision'] == 2 for r in rows)
        assert all('LATEST EDIT.' in r.prompt_snapshot['text'] for r in rows)
        frozen = deepcopy(rows[0].prompt_snapshot)
        version.config_json = config(); version.is_active = False; db.commit()
        assert prompt_service.read_snapshot(rows[0])[0] == frozen['text']
        public = service.serialize_session(db, service.get_session(db, session.id), include_internal=True)
        assert public['results'][0]['prompt_version']['revision'] == 2
        assert 'LATEST EDIT.' not in json.dumps(public, default=str)


@pytest.mark.parametrize('failure', ['disabled', 'missing', 'corrupt', 'no_default'])
def test_invalid_version_never_creates_tasks_or_charges_quota(db, monkeypatch, failure):
    seed_versions(db)
    launched = []
    monkeypatch.setattr(router_module, 'launch_composite_threads', lambda *args: launched.append(args))
    with _client(db) as (client, user):
        store = _make_store(db, user.id)
        session = _make_session(db); wig = _make_wig(db)
        version = db.get(ExpoPromptVersion, 2)
        selected = 2
        if failure == 'disabled': version.is_active = False
        if failure == 'missing': selected = 99999
        if failure == 'corrupt': version.config_json = {'parts': {}}
        if failure == 'no_default': db.get(ExpoPromptVersion, 1).default_slot = None; selected = None
        db.commit()
        response = client.post(f'/api/expo/sessions/{session.id}/generate', json={'wig_ids': [wig.id], 'prompt_version_id': selected})
        assert response.status_code in (404, 409), response.text
        db.expire_all()
        assert store.used_quota == 0 and db.query(ExpoResult).count() == 0 and not launched
        assert session.status == 'analyzed' and session.store_id is None


def test_worker_sends_saved_prompt_even_after_version_changes(db, monkeypatch, tmp_path):
    seed_versions(db)
    session = _make_session(db); wig = _make_wig(db)
    rows = ai_pipeline.build_composite_rows(session.id, [wig.id])
    prompt_service.capture_batch(db, session, rows, 1)
    db.add_all(rows); db.commit()
    expected = rows[0].prompt_snapshot['text']
    version = db.get(ExpoPromptVersion, 1); version.config_json = {}; db.commit()
    captured = []
    monkeypatch.setattr(ai_pipeline, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    monkeypatch.setattr(ai_pipeline, '_prep_image', lambda path: str(path))
    monkeypatch.setattr('app.ai.service.edit_image', lambda **kw: captured.append(kw) or {})
    target = ai_pipeline.RESULT_DIR / 'test_saved_prompt.png'
    monkeypatch.setattr(ai_pipeline, '_save_result_image', lambda *args: target)
    monkeypatch.setattr(ai_pipeline, 'stamp_logo', lambda *args: None)
    monkeypatch.setattr(ai_pipeline, 'make_display_image', lambda *args: None)
    monkeypatch.setattr(ai_pipeline, '_refresh_session_status', lambda *args: None)
    ai_pipeline._run_composite(session.id, rows[0].id)
    assert len(captured) == 1 and captured[0]['prompt'] == expected
    assert rows[0].status == 'done'


def test_migration_seeds_complete_configs_and_preserves_history():
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / 'alembic/versions/139_expo_prompt_versions.py'
    spec = importlib.util.spec_from_file_location('migration_139', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE ark_users (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE ark_expo_results (id INTEGER PRIMARY KEY, prompt_variant VARCHAR(16), image_path VARCHAR(512))'))
        connection.execute(sa.text("INSERT INTO ark_expo_results VALUES (7, 'soft', 'historical.jpg')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT prompt_variant, image_path, prompt_snapshot, prompt_version_id FROM ark_expo_results')).one() == ('soft', 'historical.jpg', None, None)
        configs = connection.execute(sa.text('SELECT config_json FROM ark_expo_prompt_versions')).scalars().all()
        assert len(configs) == 3
        for value in configs: PromptConfig.model_validate(json.loads(value))
        assert connection.execute(sa.text('SELECT id FROM ark_expo_prompt_versions WHERE default_slot = 1')).scalar_one() == 1
    engine.dispose()


def test_version_audit_time_is_beijing_across_utc_midnight(db, monkeypatch):
    from datetime import datetime, timezone
    from app.core import time as time_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 9, 6, 16, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(time_module, 'datetime', Clock)
    seed_versions(db)
    row = db.get(ExpoPromptVersion, 1)
    assert row.created_at == datetime(2026, 9, 7, 0, 1)
    updated = prompt_service.update_version(db, 1, PromptVersionUpdate(name=row.name,
        config=config(), expected_revision=1), None)
    assert updated.updated_at == datetime(2026, 9, 7, 0, 1)


def test_quota_race_rolls_back_snapshot_and_results(db, monkeypatch):
    from app.expo.quota_service import InsufficientQuota
    seed_versions(db)
    def exhausted(*args, **kwargs):
        raise InsufficientQuota('quota was consumed by another request')
    monkeypatch.setattr(router_module.quota_service, 'deduct_quota', exhausted)
    with _client(db) as (client, user):
        store = _make_store(db, user.id); session = _make_session(db); wig = _make_wig(db)
        response = client.post(f'/api/expo/sessions/{session.id}/generate', json={'wig_ids': [wig.id], 'prompt_version_id': 1})
        assert response.status_code == 400
        db.expire_all()
        assert db.query(ExpoResult).count() == 0 and store.used_quota == 0 and session.status == 'analyzed'


def test_preview_scene_ignores_unused_wig_and_color(db):
    from app.expo.prompt_schemas import PromptPreviewRequest
    result = prompt_service.preview(db, PromptPreviewRequest(config=config(), mode='scene',
        scene_key='cafe', wig_id=99999, hair_color_id=99999))
    assert result['image_count'] == 1 and 'coffee shop' in result['prompt']
