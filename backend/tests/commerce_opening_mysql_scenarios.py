"""Called by the real full-chain fixture; no ORM-cloned schema substitutes."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event, Lock
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from app.commerce_migration import inventory_service as opening_service
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.semifinished import inventory_service, order_service
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger, SemifinishedOrderItem


def verify_semifinished_opening_races(engine, user_id):
    user = dict(sub=str(user_id), roles=['super_admin'], permissions=[])
    evidence = []
    for action in ['receive', 'adjust']:
        for shared in [True, False]:
            tag = f'{action}-{shared}'
            with Session(engine) as db:
                ids = []
                for index in range(2):
                    master = SemifinishedMaterial(material_code=f'RACE-{tag}-{index}', size='20',
                        color_code=f'{tag}-{index}', color_key=f'{tag}-{index}')
                    db.add(master); db.flush()
                    db.add(InventoryBalance(material_id=master.id))
                    ids.append(master.id)
                db.commit()
                target = ids[0 if shared else 1]
                order = order_service.create_order(db, items=[dict(material_id=target, quantity_grams=Decimal('20'))], user_id=user_id)
                item_id = order.items[0].id
            body = InventoryOpeningManifest(batch_key=f'opening-race-{tag}', source='verified-export', tenant='test',
                cutover_date='2026-10-03', evidence_sha256='c' * 64, review_reference='Synthetic first movement race',
                materials=[dict(external_id=tag, mode='initialize', material_id=ids[0], on_hand_grams='100.000')])
            gate, seen, mutex, opening_balance = Barrier(2), set(), Lock(), Event()
            def synchronize_balance(conn, _cursor, statement, _parameters, _context, _many):
                label = conn.info.get('opening_race_label')
                sql = statement.lower()
                if label not in {'opening', 'ordinary'} or 'ark_commerce_transition_policy' not in sql or not sql.lstrip().startswith('update'):
                    return
                with mutex:
                    if label in seen:
                        return
                    seen.add(label)
                # Both requests have established RR views and reached the policy
                # mutex attempt. The policy intentionally serializes balances;
                # waiting for both balance locks would deadlock the test itself.
                gate.wait(timeout=15)
                if label == 'ordinary':
                    assert opening_balance.wait(timeout=15)
            def mark_opening_balance(conn, _cursor, statement, _parameters, _context, _many):
                sql = statement.lower()
                if conn.info.get('opening_race_label') == 'opening' and 'ark_commerce_transition_policy' in sql and sql.lstrip().startswith('update'):
                    opening_balance.set()
            event.listen(engine, 'before_cursor_execute', synchronize_balance)
            event.listen(engine, 'after_cursor_execute', mark_opening_balance)
            def worker(label):
                with Session(engine) as db:
                    conn = db.connection()
                    connection_info = conn.info
                    connection_info['opening_race_label'] = label
                    db.scalar(select(func.count()).select_from(InventoryLedger))  # Establish RR view.
                    try:
                        if label == 'opening':
                            result = opening_service.apply_manifest(db, body, user)
                        elif action == 'receive':
                            result = order_service.receive_item(db, item_id=item_id, quantity_grams=Decimal('10'),
                                idempotency_key=f'ordinary-{tag}', operator_id=user_id, remark='Synthetic normal receipt')
                        else:
                            row = inventory_service.adjust_inventory(db, material_id=target, quantity_grams=Decimal('10'),
                                idempotency_key=f'ordinary-{tag}', operator_id=user_id, remark='Synthetic normal adjustment')
                            result = row.id
                        db.commit()
                        return ('ok', result)
                    except ValueError:
                        db.rollback()
                        return ('rejected', None)
                    finally:
                        connection_info.pop('opening_race_label', None)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    result = list(pool.map(worker, ['opening', 'ordinary']))
            finally:
                event.remove(engine, 'before_cursor_execute', synchronize_balance)
                event.remove(engine, 'after_cursor_execute', mark_opening_balance)
            assert result[1][0] == 'ok'
            assert result[0][0] == 'ok'
            with Session(engine) as db:
                for material_id in ids:
                    balance = db.scalar(select(InventoryBalance).where(InventoryBalance.material_id == material_id))
                    rows = db.scalars(select(InventoryLedger).where(InventoryLedger.material_id == material_id).order_by(InventoryLedger.id)).all()
                    assert balance.version == len(rows)
                    assert balance.on_hand_grams == sum((row.quantity_grams for row in rows), Decimal(0))
                    if rows:
                        assert rows[-1].on_hand_after == balance.on_hand_grams
                actual = db.scalar(select(InventoryBalance.on_hand_grams).where(InventoryBalance.material_id == ids[0]))
                if shared:
                    assert actual == Decimal('110')
                else:
                    assert actual == Decimal('100')
                if action == 'receive':
                    assert db.get(SemifinishedOrderItem, item_id).received_qty_grams == Decimal('10')
            evidence.append(dict(action=action, shared_material=shared, opening=result[0][0], ordinary=result[1][0], opening_acquired_balance_first=True))
    replay_results = []
    for action in ['receive', 'adjust']:
        with Session(engine) as db:
            master = SemifinishedMaterial(material_code=f'REPLAY-{action}', size='22', color_code=action, color_key=action)
            db.add(master); db.flush()
            material_id = master.id
            db.add(InventoryBalance(material_id=material_id)); db.commit()
            order = order_service.create_order(db, items=[dict(material_id=material_id, quantity_grams=Decimal('20'))], user_id=user_id)
            item_id = order.items[0].id
        gate = Barrier(2)
        def replay_worker(_):
            with Session(engine) as db:
                db.scalar(select(func.count()).select_from(InventoryLedger))
                gate.wait(timeout=15)
                if action == 'receive':
                    result = order_service.receive_item(db, item_id=item_id, quantity_grams=Decimal('10'),
                        idempotency_key=f'concurrent-replay-{action}', operator_id=user_id, remark='Same body')
                    return result['ledger_id']
                row = inventory_service.adjust_inventory(db, material_id=material_id, quantity_grams=Decimal('10'),
                    idempotency_key=f'concurrent-replay-{action}', operator_id=user_id, remark='Same body')
                return row.id
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(replay_worker, range(2)))
        assert ids[0] == ids[1]
        with Session(engine) as db:
            assert db.scalar(select(InventoryBalance.on_hand_grams).where(InventoryBalance.material_id == material_id)) == Decimal('10')
            assert db.scalar(select(func.count()).select_from(InventoryLedger).where(InventoryLedger.material_id == material_id)) == 1
            before = db.scalar(select(func.count()).select_from(InventoryLedger))
            try:
                if action == 'receive':
                    order_service.receive_item(db, item_id=item_id, quantity_grams=Decimal('11'),
                        idempotency_key=f'concurrent-replay-{action}', operator_id=user_id, remark='Same body')
                else:
                    inventory_service.adjust_inventory(db, material_id=material_id, quantity_grams=Decimal('11'),
                        idempotency_key=f'concurrent-replay-{action}', operator_id=user_id, remark='Same body')
            except ValueError:
                pass
            else:
                raise AssertionError('A changed body reused the original movement')
            db.commit()
            assert db.scalar(select(func.count()).select_from(InventoryLedger)) == before
            assert db.scalar(select(InventoryBalance.on_hand_grams).where(InventoryBalance.material_id == material_id)) == Decimal('10')
        replay_results.append(dict(action=action, same_key_one_movement=True, changed_body_rejected=True))
    # A net-zero change cannot make a stale RR sum into complete evidence.
    with Session(engine) as stale:
        stale.scalar(select(func.count()).select_from(InventoryLedger))
        for index, delta in enumerate([Decimal('2'), Decimal('-2')]):
            with Session(engine) as db:
                inventory_service.adjust_inventory(db, material_id=material_id, quantity_grams=delta,
                    idempotency_key=f'net-zero-{index}', operator_id=user_id, remark='Net zero history')
        body = InventoryOpeningManifest(batch_key='old-rr-acknowledge', source='verified-export', tenant='test',
            cutover_date='2026-10-03', evidence_sha256='c' * 64, review_reference='Synthetic RR completeness',
            materials=[dict(external_id='net-zero', mode='acknowledge_existing', material_id=material_id, on_hand_grams='10.000')])
        report = opening_service.preview(stale, body, lock=True)
        assert not report['can_apply'] and '快照已过期' in report['conflicts'][0]['message']
        stale.rollback()
    with Session(engine) as db:
        assert opening_service.preview(db, body)['can_apply']
        opening_service.apply_manifest(db, body, user); db.commit()
        assert db.scalar(select(InventoryBalance.on_hand_grams).where(InventoryBalance.material_id == material_id)) == Decimal('10')
    return dict(opening_vs_ordinary=evidence, ordinary_concurrent_replays=replay_results, stale_rr_net_zero_acknowledgment_rejected=True)
