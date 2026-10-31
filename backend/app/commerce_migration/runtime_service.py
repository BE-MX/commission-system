"""An existing native journal forbids restarting with the legacy authority."""
import json
from sqlalchemy import inspect, text


JOURNALS = ('ark_stock_ledger', 'ark_finance_events', 'ark_invoice_commerce_events', 'ark_production_events')


def verify_transaction_authority(engine, mode, expected_phase=None):
    if mode not in {'legacy', 'local'}:
        raise RuntimeError('交易主系统模式无效')
    with engine.connect() as connection:
        inspector = inspect(connection)
        present = set(inspector.get_table_names())
        installed_phase = None
        if 'ark_commerce_transition_policy' in present:
            policy = connection.execute(text('SELECT phase,version,min_writer_version,writer_inventory_verified,inventory_evidence '
                'FROM ark_commerce_transition_policy WHERE id=1')).mappings().one_or_none()
            if not policy or policy['phase'] not in {'legacy_only', 'transition', 'local_only'} or policy['version'] < 1:
                raise RuntimeError('持久交易阶段无效，禁止启动交易服务')
            installed_phase = policy['phase']
            if expected_phase is not None and expected_phase != installed_phase:
                raise RuntimeError('进程声明的交易阶段与持久策略不一致')
            if installed_phase != 'legacy_only':
                evidence = policy['inventory_evidence']
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except (ValueError, TypeError):
                        evidence = None
                if not policy['writer_inventory_verified'] or not isinstance(evidence, dict) or not evidence:
                    raise RuntimeError('独立交易writer清单尚未核验')
                writers = connection.execute(text('SELECT protocol_version,status FROM ark_commerce_writer_receipts')).mappings().all()
                if not writers or any(row['status'] != 'revoked' and (row['status'] != 'compatible'
                        or row['protocol_version'] < policy['min_writer_version']) for row in writers):
                    raise RuntimeError('存在未兼容或未撤权的交易writer')
        elif expected_phase is not None or mode == 'local':
            raise RuntimeError('交易办理权迁移尚未安装')
        native_facts = {}
        for table in JOURNALS:
            if table in present:
                native_facts[table] = bool(connection.scalar(text(f'SELECT 1 FROM `{table}` LIMIT 1')))
        for table, label in [('ark_invoices', 'local_orders'), ('ark_production_orders', 'local_production_orders')]:
            if table not in present:
                continue
            columns = {column['name'] for column in inspector.get_columns(table)}
            if 'transaction_mode' in columns:
                native_facts[label] = bool(connection.scalar(text(
                    f"SELECT 1 FROM `{table}` WHERE transaction_mode='local' LIMIT 1")))
        if 'ark_commerce_migration_records' in present:
            native_facts['opening_responsibilities'] = bool(connection.scalar(text(
                "SELECT 1 FROM ark_commerce_migration_records WHERE role='opening' LIMIT 1")))
        if ((installed_phase == 'legacy_only' or (installed_phase is None and mode == 'legacy'))
                and any(native_facts.values())):
            raise RuntimeError('已有本地交易或期初责任，禁止恢复旧交易模式；保留现有账本并向前恢复')
        return dict(transaction_mode=mode, phase=installed_phase, native_facts=native_facts)
