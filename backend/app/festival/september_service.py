"""September 2026 customer targets, independent of August points and camp awards.

OKKI is the authoritative order/status source for this screen. All queries are
read-only; monthly totals are rebuilt so invalid orders are removed on refresh.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
import logging

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.time import beijing_now_aware, beijing_today
from app.festival import service

logger = logging.getLogger(__name__)
START = date(2026, 9, 1)
END = date(2026, 9, 30)
JIASHU_USER_ID = '55951723'  # 周露露; legacy roster label is 个人队.
TARGETS = (
    ('乘风', 21), ('行则将至', 15), ('星星之火', 11), ('无名', 10),
    ('稻乐偲', 14), ('专治不服', 15), ('多财多亿', 22), ('嘉树', 5),
)


def champion_names(groups: list[dict]) -> list[str]:
    eligible = [g for g in groups if not g['solo'] and g['members'] >= 2
                and g['target'] > 0 and g['done'] >= g['target']]
    if not eligible:
        return []
    def score(group):
        return Fraction(group['done'], group['target']), group['_amount']
    best = max(map(score, eligible))
    return [g['name'] for g in eligible if score(g) == best]


def _roster(db: Session, issues: dict) -> tuple[dict, dict]:
    rows = db.execute(text('SELECT t.user_id, t.Team AS team FROM lsordertest.user_rel_team t '
                           'WHERE 1=1' + service._active_roster_filter('t'))).mappings().all()
    names = {name for name, _ in TARGETS}
    assignments = defaultdict(set)
    for row in rows:
        uid = str(row['user_id'] or '').strip()
        team = str(row['team'] or '').strip()
        if uid == JIASHU_USER_ID and team in ('个人队', '嘉树'):
            team = '嘉树'
        # 嘉树 is a named individual, not a catch-all for any personal participant.
        if not uid or team not in names or (team == '嘉树' and uid != JIASHU_USER_ID):
            issues['unassigned_members'] += 1
        assignments[uid].add(team)
    owners = {}
    members = defaultdict(set)
    for uid, teams in assignments.items():
        if len(teams) != 1:
            issues['conflicting_members'] += 1
            continue
        team = next(iter(teams))
        if team in names and uid and (team != '嘉树' or uid == JIASHU_USER_ID):
            owners[uid] = team
            members[team].add(uid)
    issues['missing_groups'] = sum(not members[name] for name, _ in TARGETS)
    return owners, members


def _effective_amount(raw_values: list, issues: dict) -> Decimal | None:
    try:
        values = [Decimal(str(value)) for value in raw_values]
        if not all(value.is_finite() for value in values):
            raise ValueError('non-finite amount')
    except (InvalidOperation, ValueError):
        # Report and log the aggregate data issue from get_payload, without client details.
        issues['invalid_amounts'] += 1
        return None
    net = sum(values, Decimal(0))
    # Free samples count; a full reversal or standalone negative correction does not.
    return None if any(value < 0 for value in values) and net <= 0 else net


def _orders(db: Session, user_ids: list[str], end: date, issues: dict) -> tuple[list, set]:
    if not user_ids or end < START:
        return [], set()
    stmt = text(
        'SELECT o.order_id, o.company_id AS customer_id, o.user_id, o.amount_usd AS amount '
        'FROM lsordertest.okki_orders o WHERE o.user_id IN :ids '
        'AND o.account_date >= :start AND o.account_date <= :end '
        'AND o.custom_fields LIKE :mark' + service._common_filter('o')
    ).bindparams(bindparam('ids', expanding=True))
    rows = db.execute(stmt, {'ids': user_ids, 'start': START.isoformat(),
                            'end': end.isoformat(), 'mark': service.NEW_SIGN_MARK}).mappings().all()
    customers = sorted({str(r['customer_id']) for r in rows if r['customer_id']})
    if not customers:
        return rows, set()
    # Check the whole historical customer pool, not just current roster members.
    # A repeated "new deal" flag in September must not re-count an August client.
    prior = text(
        'SELECT o.company_id, o.amount_usd FROM lsordertest.okki_orders o '
        'WHERE o.company_id IN :ids AND o.account_date < :start '
        + service._common_filter('o')
    ).bindparams(bindparam('ids', expanding=True))
    historical_amounts = defaultdict(list)
    for cid, amount in db.execute(prior, {'ids': customers, 'start': START.isoformat()}):
        historical_amounts[str(cid)].append(amount)
    old = {cid for cid, amounts in historical_amounts.items()
           if _effective_amount(amounts, issues) is not None}
    return rows, old


def _rate(done: int, target: int) -> float:
    return float((Decimal(done) * 100 / Decimal(target)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def get_payload(db: Session, *, finalized: bool = False) -> dict:
    today = beijing_today()
    issues = defaultdict(int)
    owners, members = _roster(db, issues)
    rows, old_customers = _orders(db, list(owners), min(today, END), issues)
    customers = defaultdict(list)
    for row in rows:
        cid = str(row['customer_id'] or '').strip()
        if not cid:
            issues['missing_customers'] += 1
        elif cid not in old_customers:
            customers[cid].append(row)

    counts = defaultdict(int)
    amounts = defaultdict(Decimal)
    for orders in customers.values():
        teams = {owners[str(o['user_id'])] for o in orders}
        if len(teams) != 1:
            issues['conflicting_customers'] += 1
            continue
        net = _effective_amount([o['amount'] for o in orders], issues)
        if net is None:
            continue
        team = next(iter(teams))
        counts[team] += 1
        amounts[team] += net

    groups = []
    for name, target in TARGETS:
        done = counts[name]
        groups.append({
            'name': name, 'target': target, 'done': done, 'rate': _rate(done, target),
            'members': len(members[name]), 'solo': name == '嘉树',
            'achieved': done >= target, 'remaining': max(target - done, 0),
            'excess': max(done - target, 0), '_amount': amounts[name],
        })
    clean = not any(issues.values())
    winners = champion_names(groups) if clean else []
    winner_groups = [g for g in groups if g['name'] in winners]
    same_rate = winner_groups and sum(
        not g['solo'] and g['members'] >= 2 and g['done'] >= g['target']
        and g['done'] * winner_groups[0]['target'] == winner_groups[0]['done'] * g['target']
        for g in groups
    ) > 1
    phase = ('upcoming' if today < START else 'ongoing' if today <= END
             else 'finalized' if finalized else 'pending_review')
    for group in groups:
        group['first'] = group['name'] in winners
        del group['_amount']  # No money, employee or customer details in the public payload.
    total = sum(g['done'] for g in groups)
    target = sum(g['target'] for g in groups)
    if not clean:
        message = f'September screen data requires review: {dict(issues)}'
        logger.warning(message)
        print(message, flush=True)
    return {
        'period': {'start': START.isoformat(), 'end': END.isoformat()},
        'phase': phase, 'source': 'okki',
        'groups': groups,
        'total': {'target': target, 'done': total if clean else None,
                  'rate': _rate(total, target) if clean else None,
                  'remaining': max(target - total, 0) if clean else None,
                  'excess': max(total - target, 0) if clean else None,
                  'achieved_groups': sum(g['achieved'] for g in groups) if clean else None,
                  'group_count': len(groups)},
        'champion': {'state': 'data_issue' if not clean else 'first' if winners else 'vacant',
                     'names': winners, 'tied': len(winners) > 1,
                     'by_revenue': bool(same_rate and len(winners) == 1)},
        'data_quality': {'ok': clean, 'counts': {k: v for k, v in issues.items() if v},
                         'message': '' if clean else '数据待核对 · 总进度与第一评选暂停，已归属数据仅供核对'},
        'as_of': beijing_now_aware().isoformat(timespec='seconds'),
    }
