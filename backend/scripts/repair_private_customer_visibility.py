"""Apply a reviewed private-customer scope through existing audited services.

The frozen plan comes from a read-only inspection. Source ownership is checked
again for each customer. Existing primary ownership is never transferred.
No research tasks, AI calls, source writes or application deployment occur.
"""
import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUserRole
from app.auth.admin_router import _write_permission_audit
from app.core.database import SessionLocal
from app.customer.logical_customer_service import resolve_canonical_customer_id
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.customer.profile_service import compile_customer_profile
from app.customer.projection_common import ProjectionRetryRequired
from scripts.sync_okki_private_pool import (
    OKKI_ACCOUNT_KEY, _active_user, _business_schema, _resolve_okki_owner,
    _sync_one_customer,
)

logger = logging.getLogger(__name__)


def grant_customer_read(db, operator):
    """Add exactly one permission; lock the role and preserve existing links."""
    role = db.query(ArkRole).filter(ArkRole.name == 'salesperson').with_for_update().one()
    permission = db.query(ArkPermission).filter(ArkPermission.code == 'customer:read').one()
    old = {row.permission_id for row in db.query(ArkRolePermission).filter(
        ArkRolePermission.role_id == role.id)}
    if permission.id in old:
        return False
    db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    _write_permission_audit(db, role, {'sub': str(operator.id),
        'username': operator.username}, old, old | {permission.id})
    db.flush()
    return True


def choose_primary(target_ids, existing_primary):
    """Keep a known primary; never infer primary ownership for shared customers."""
    if existing_primary is not None:
        return (existing_primary, None) if existing_primary in target_ids else (None, 'ownership_conflict')
    if len(target_ids) == 1:
        return target_ids[0], None
    return None, 'needs_primary_review'


def repair_customer(db, item, operator, *, with_orders):
    company_id = str(item['company_id'])
    source = db.execute(text(f'SELECT company_name, owner_user_ids, update_time '
        f'FROM `{_business_schema()}`.customer_info WHERE company_id=:cid'),
        {'cid': company_id}).mappings().one_or_none()
    if source is None:
        return {'company_id': company_id, 'status': 'source_missing'}
    values = source['owner_user_ids']
    values = json.loads(values) if isinstance(values, str) else (values or [])
    if set(map(str, values)) != set(map(str, item['owner_user_ids'])):
        return {'company_id': company_id, 'status': 'source_owner_changed'}
    users = {}
    salesperson = db.query(ArkRole.id).filter(ArkRole.name == 'salesperson').scalar()
    for target in item['targets']:
        user, okki_id = _resolve_okki_owner(db, target['username'])
        if user.id != target['id'] or okki_id != str(target['external_account_id']) or str(okki_id) not in set(map(str, values)):
            return {'company_id': company_id, 'status': 'binding_changed'}
        if db.query(ArkUserRole).filter(ArkUserRole.user_id == user.id,
                ArkUserRole.role_id == salesperson).first() is None:
            return {'company_id': company_id, 'status': 'role_changed'}
        users[user.id] = user
    identity = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.source_system == 'okki',
        CustomerExternalIdentity.source_account_key == OKKI_ACCOUNT_KEY,
        CustomerExternalIdentity.identifier_type == 'company_id',
        CustomerExternalIdentity.normalized_value == company_id,
        CustomerExternalIdentity.status == 'active').one_or_none()
    canonical_id = resolve_canonical_customer_id(db, identity.customer_id) if identity else None
    if canonical_id:
        db.query(CustomerAccount).filter(CustomerAccount.id == canonical_id).with_for_update().one()
    primary = db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == canonical_id,
        CustomerAssignment.assignment_role == 'primary',
        CustomerAssignment.assignment_status == 'active',
        CustomerAssignment.effective_to.is_(None)).with_for_update().one_or_none() if canonical_id else None
    chosen, reason = choose_primary(list(users), primary.user_id if primary else None)
    if reason:
        return {'company_id': company_id, 'status': reason,
            'existing_primary': primary.user_id if primary else None,
            'target_ids': list(users)}
    row = {'company_id': company_id, 'company_name': source['company_name'],
        'update_time': source['update_time']}
    result = _sync_one_customer(db, row, owner=users[chosen], operator=operator,
        with_orders=with_orders)
    if not result.get('assigned'):
        db.rollback()
        return {**result, 'status': 'assignment_failed'}
    if result.get('orders', {}).get('quarantined'):
        db.rollback()
        return {**result, 'status': 'order_projection_quarantined'}
    if len(users) > 1:
        from app.customer.workflow_service import assign_customer
        for user_id in users:
            if user_id != chosen:
                assign_customer(db, customer_id=result['customer_id'], user_id=user_id,
                    assignment_role='collaborator', assignment_source='import',
                    operated_by=operator.id, change_reason='OKKI shared private customer visibility repair')
    return {**result, 'status': 'projected', 'target_ids': list(users)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--owner', help='Process only this owner from the reviewed scope')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
    items = plan['customers']
    if args.owner:
        items = [item for item in items if any(t['username'] == args.owner for t in item['targets'])]
    items = sorted(items, key=lambda item: (not any(t['username'] == 'Derek' for t in item['targets']), int(item['company_id'])))
    if not args.apply:
        print(json.dumps({'dry_run': True, 'customers': len(items),
            'shared': sum(len(item['targets']) > 1 for item in items)}))
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        operator = _active_user(db, args.operator)
        if not any(role.name in {'admin', 'super_admin'} for role in operator.roles):
            raise ValueError('OPERATOR_ADMIN_REQUIRED')
        permission_added = grant_customer_read(db, operator)
        db.commit()
        print(json.dumps({'permission_added': permission_added}), flush=True)
        counts = Counter()
        with args.output.open('a', encoding='utf-8') as output:
            for index, item in enumerate(items, 1):
                result = None
                for attempt in range(2):
                    try:
                        result = repair_customer(db, item, operator, with_orders=False)
                        db.commit()
                        break
                    except ProjectionRetryRequired:
                        db.rollback()
                        if attempt == 1:
                            result = {'company_id': item['company_id'], 'status': 'projection_retry_exhausted'}
                    except Exception as exc:
                        db.rollback()
                        logger.warning('Private visibility repair failed: %s', type(exc).__name__)
                        print(f'Private visibility repair failed: {type(exc).__name__}', flush=True)
                        result = {'company_id': item['company_id'], 'status': 'failed', 'error_type': type(exc).__name__}
                        break
                if result['status'] == 'projected':
                    try:
                        compiled = compile_customer_profile(SessionLocal, int(result['customer_id']))
                        result['profile_version_id'] = compiled.profile_version_id
                        result['projection_statuses'] = {name: state.status for name, state in compiled.projections.items()}
                        result['status'] = 'completed' if all(state.status == 'current' for state in compiled.projections.values()) else 'profile_projection_failed'
                    except Exception as exc:
                        logger.warning('Private visibility profile failed: %s', type(exc).__name__)
                        print(f'Private visibility profile failed: {type(exc).__name__}', flush=True)
                        result['status'] = 'profile_failed'
                        result['error_type'] = type(exc).__name__
                counts[result['status']] += 1
                output.write(json.dumps(result, ensure_ascii=False, default=str) + '\n')
                output.flush()
                print(json.dumps({'progress': index, 'total': len(items), 'counts': dict(counts)}), flush=True)
        if any(status not in {'completed', 'needs_primary_review', 'ownership_conflict'} for status in counts):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
