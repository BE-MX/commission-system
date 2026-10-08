"""Spawn-only persisted proposal worker; owned DB credentials use IPC, never logs."""
def run(url, settings, clock_utc, server_zone, command, output):
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from decimal import Decimal
    from uuid import uuid4
    import pymysql
    from sqlalchemy import create_engine, event, select, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session
    import conftest as isolation
    engine = None
    try:
        assert not (Path(__file__).resolve().parents[2] / '.env').exists()
        isolation.ALLOWED.update(port=url.port, password=url.password, database=url.database)
        pymysql.connect = isolation.isolated_connect
        event.listen(Engine, 'do_connect', isolation.isolated_engine)
        import mysql_service_fixture  # noqa: F401; register upstream models, no seed
        from app.core import time as platform_time
        from app.portal import (auth_service as auth, authority, admin_service, quote_service,
            catalog_service, pricing, sku_source, order_queries, proposal_decisions, approval_service, invoice_adapter)
        from app.portal.errors import PortalError
        from app.portal.inventory import InventoryObservation
        from app.portal.models import OrderRequest, Revision, RequestLine, Quote
        from app.portal.schemas import AcceptInput, ApproveInput
        from app.portal import revision_evidence
        config = SimpleNamespace(**settings)
        for module in (auth, authority, admin_service, quote_service, catalog_service, pricing, sku_source, order_queries):
            module.get_settings = lambda: config
        class ProcessClock(datetime):
            @classmethod
            def now(cls, tz=None):
                value = clock_utc.astimezone(tz or ZoneInfo(server_zone))
                return value if tz is not None else value.replace(tzinfo=None)
        # Deterministic application clock with a non-Beijing default server zone;
        # no machine clock/Windows timezone change is made.
        platform_time.datetime = ProcessClock
        catalog_service.load_observations = lambda db, rows: {row.public_id:InventoryObservation(
            Decimal('1000'),'g',platform_time.beijing_now(),'synthetic-test-mirror') for row in rows}
        sku_source.product_service._schema = lambda:'portal_isolated_test'
        invoices = invoice_adapter.invoices
        invoices.resolve_okki_flags = lambda *args:{'okki_new_deal':1,'okki_free_shipping':0,'okki_first_return':0}
        invoices.get_customer_grade = lambda *args:None
        invoices.suggest_invoice_no = lambda *args:'PI-RESTART-'+uuid4().hex
        invoices.product_service.valid_okki_product_skus = lambda db,pairs:pairs
        engine = create_engine(url,isolation_level='REPEATABLE READ',hide_parameters=True)
        @event.listens_for(engine,'connect')
        def configure(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
                cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        with Session(engine) as db:
            if command['operation'] == 'read_snapshots':
                evidence = {}
                for identifier in command['quotes']:
                    quote = db.scalar(select(Quote).where(Quote.public_id == identifier))
                    verified = quote_service.view(quote)
                    evidence[identifier] = {'kind':'quote', 'expires_at':quote.expires_at.isoformat(),
                        'content_hash':verified['content_hash'], 'payment_terms':quote.payment_terms_snapshot}
                for identifier in command['revisions']:
                    revision = db.scalar(select(Revision).where(Revision.public_id == identifier))
                    lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id)).all()
                    revision_evidence.verify(revision, lines)
                    evidence[identifier] = {'kind':revision.kind, 'expires_at':revision.expires_at.isoformat(),
                        'content_hash':revision.content_hash, 'payment_terms':revision.payment_terms_snapshot}
                output.put(('snapshots', os.getpid(), db.scalar(text('SELECT CONNECTION_ID()')), evidence,
                    platform_time.beijing_now().isoformat(), ProcessClock.now().isoformat()))
                db.rollback()
                return
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == command['request_id']))
            revision = db.get(Revision,order.active_revision_id)
            lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id)).all()
            revision_evidence.verify(revision,lines)
            evidence = {'expires_at':revision.expires_at.isoformat(),'payment_terms':revision.payment_terms_snapshot,
                'content_hash':revision.content_hash,'accepted_by':revision.customer_accepted_by}
            output.put(('loaded',os.getpid(),db.scalar(text('SELECT CONNECTION_ID()')),evidence,
                platform_time.beijing_now().isoformat(),ProcessClock.now().isoformat()))
            db.rollback()
            try:
                if command['operation'] == 'accept':
                    result = proposal_decisions.decide(db,command['token'],command['csrf'],command['request_id'],command['revision_id'],
                        command['version'],AcceptInput(proposal_hash=command['hash']),accept=True)
                else:
                    result = approval_service.approve(db,command['actor'],command['request_id'],command['version'],
                        ApproveInput(accepted_revision_id=command['revision_id']))
                db.commit(); output.put(('success',result))
            except PortalError as error:
                db.rollback(); output.put(('denied',error.code,error.status))
    except Exception as error:
        output.put(('worker_error',type(error).__name__))
    finally:
        if engine is not None: engine.dispose()