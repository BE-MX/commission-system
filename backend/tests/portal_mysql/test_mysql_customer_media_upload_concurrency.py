"""Owned loopback MySQL RR races through the real upload finalization path.

Auth/tag adapters are outside this race; batch, directory and asset SQL is real.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import ForeignKeyConstraint, MetaData, event, inspect, select, text
from sqlalchemy.orm import Session

from app.customer_media import service
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaBatch, CustomerMediaDirectory, CustomerMediaReview,
)
from app.customer_media.storage import StoredUpload


def _is_capacity_read(statement):
    sql = ' '.join(statement.lower().split())
    return ('from ark_customer_media_assets' in sql and
        (sql.startswith('select ark_customer_media_assets.file_size ') or
         sql.startswith('select coalesce(sum(ark_customer_media_assets.file_size)')))


@pytest.fixture
def media_tables(mysql_engine, monkeypatch):
    # Keep real column types/indexes; external auth/design/tag domains are not
    # part of this isolation-level test and are replaced below.
    metadata = MetaData()
    models = (CustomerMediaBatch, CustomerMediaDirectory, CustomerMediaAsset, CustomerMediaReview)
    existing = set(inspect(mysql_engine).get_table_names())
    if existing.intersection(model.__tablename__ for model in models):
        pytest.skip('Requires absent media tables; never replaces tables from another suite')
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for constraint in list(table.constraints):
            if isinstance(constraint, ForeignKeyConstraint):
                table.constraints.remove(constraint)
        table.foreign_keys.clear()
        for column in table.columns:
            column.foreign_keys.clear()
    metadata.create_all(mysql_engine)
    monkeypatch.setattr(service, 'user_identity', lambda *_: (1, [], []))
    monkeypatch.setattr(service, '_load_task', lambda *_: (object(), None))
    monkeypatch.setattr(service, '_assert_writer', lambda *_: None)
    monkeypatch.setattr(service, '_insert_asset_tags', lambda *_: None)
    monkeypatch.setattr(service, '_validate_customer_tag_items', lambda *_, **__: None)
    monkeypatch.setattr(service, 'get_batch', lambda _, batch_id: {'id': batch_id})
    yield mysql_engine
    metadata.drop_all(mysql_engine)


@pytest.mark.parametrize('first_directory,directory_mode', [
    ('none', 'none'), ('none', 'id'), ('none', 'name'), ('id', 'id'), ('name', 'name'),
])
@pytest.mark.parametrize('capacity,expected_count', [(10, 1), (12, 2)])
def test_two_rr_uploads_recheck_capacity_and_order(media_tables, first_directory, directory_mode, capacity, expected_count):
    engine = media_tables
    with Session(engine) as db:
        batch = CustomerMediaBatch(task_id=1, request_id=1, customer_id='customer-1',
            customer_name_snapshot='Synthetic customer', applicant_user_id=1, status='draft')
        directory = CustomerMediaDirectory(customer_id='customer-1', name='Synthetic folder', created_by=1)
        db.add_all([batch, directory]); db.commit()
        batch_id, directory_id = batch.id, directory.id
    directory_args = (directory_id, None) if directory_mode == 'id' else (
        (None, 'Synthetic folder') if directory_mode == 'name' else (None, None))

    def stored():
        return StoredUpload(provider='local', object_key=uuid4().hex + '.jpg', file_name='test.jpg',
            media_type='image', content_type='image/jpeg', file_size=6, sha256='0' * 64)

    first_at_quota, release_first = Event(), Event()
    worker = local()

    def pause_first_quota(conn, cursor, statement, parameters, context, executemany):
        if getattr(worker, 'first', False) and _is_capacity_read(statement):
            first_at_quota.set()
            assert release_first.wait(10), 'First upload was not released'

    def upload(is_first):
        worker.first = is_first
        with Session(engine) as db:
            assert db.scalar(text('SELECT @@transaction_isolation')) == 'REPEATABLE-READ'
            # Actual preparation ends its read transaction before file storage;
            # directory resolution and final transaction are real business code.
            service._prepare_upload(db, batch_id, {}, [{'dimension_id': 1, 'tag_value_ids': [1]}])
            selected = directory_args if not is_first or first_directory != 'none' else (None, None)
            try:
                return service._finish_upload(db, batch_id, {}, stored(), 1, 'customer-1',
                    capacity, *selected, [])
            except service.CustomerMediaConflict:
                db.rollback()
                return 'capacity-rejected'

    event.listen(engine, 'after_cursor_execute', pause_first_quota)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(upload, True)
            assert first_at_quota.wait(5)
            second_future = pool.submit(upload, False)
            try:
                deadline = monotonic() + 5
                with Session(engine) as observer:
                    while observer.scalar(text('SELECT COUNT(*) FROM performance_schema.data_lock_waits')) == 0:
                        assert not second_future.done(), 'Second upload did not wait on directory/batch'
                        assert monotonic() < deadline, 'Expected a real InnoDB lock wait'
                        sleep(.01)
            finally:
                release_first.set()
            outcomes = [first_future.result(timeout=10), second_future.result(timeout=10)]
        assert outcomes.count('capacity-rejected') == 2 - expected_count
        assert sum(value == {'id': batch_id} for value in outcomes) == expected_count
    finally:
        release_first.set()
        event.remove(engine, 'after_cursor_execute', pause_first_quota)
    with Session(engine) as db:
        assets = list(db.scalars(select(CustomerMediaAsset).order_by(CustomerMediaAsset.sort_order)))
        assert len(assets) == expected_count
        assert [asset.sort_order for asset in assets] == list(range(expected_count))
        assert sum(asset.file_size for asset in assets) <= capacity
        if expected_count == 2:
            assert sum(asset.directory_id == directory_id for asset in assets) == (
                int(first_directory != 'none') + int(directory_mode != 'none'))


def test_distinct_empty_batches_first_uploads_both_succeed(media_tables):
    engine = media_tables
    with Session(engine) as db:
        batches = [CustomerMediaBatch(task_id=identity, request_id=identity,
            customer_id='customer-1', customer_name_snapshot='Synthetic customer',
            applicant_user_id=1, status='draft') for identity in (1, 2)]
        db.add_all(batches); db.commit()
        ids = [batch.id for batch in batches]
    capacity_reads = Barrier(2, timeout=5)

    def align_capacity_reads(conn, cursor, statement, parameters, context, executemany):
        if _is_capacity_read(statement):
            capacity_reads.wait()

    event.listen(engine, 'after_cursor_execute', align_capacity_reads)
    try:
        def upload(batch_id):
            with Session(engine) as db:
                stored = StoredUpload(provider='local', object_key=uuid4().hex + '.jpg',
                    file_name='test.jpg', media_type='image', content_type='image/jpeg',
                    file_size=6, sha256='0' * 64)
                return service._finish_upload(db, batch_id, {}, stored, 1, 'customer-1',
                    12, None, None, [])
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(upload, identity) for identity in ids]
            results = [future.result(timeout=10) for future in futures]
        assert results == [{'id': identity} for identity in ids]
    finally:
        event.remove(engine, 'after_cursor_execute', align_capacity_reads)
    with Session(engine) as db:
        assets = list(db.scalars(select(CustomerMediaAsset)))
        assert sorted((asset.batch_id, asset.sort_order, asset.file_size) for asset in assets) == [
            (identity, 0, 6) for identity in ids]
