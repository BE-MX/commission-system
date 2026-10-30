"""Cent-exact cash matching across selected batches and shared original receipts."""
from collections import defaultdict, deque
from decimal import Decimal


def match(payments, available, batches, lines, target=None):
    mapping = {str(batch["outbound_id"]): str(batch["settlement_id"]) for batch in batches}
    credits = defaultdict(int)
    for line in lines:
        settlement = mapping.get(str(line["outbound_id"]))
        if settlement is None:
            raise ValueError("所选出库明细缺少资金批次映射")
        credits[settlement] += int(Decimal(line["reduction_amount"]) * 100)
    capacity, adjacent = {}, defaultdict(list)

    def edge(left, right, amount):
        if amount < 0:
            raise ValueError("原回款批次可退本金不能为负")
        if (left, right) not in capacity:
            adjacent[left].append(right)
            adjacent[right].append(left)
            capacity[left, right] = capacity[right, left] = 0
        capacity[left, right] += amount

    start, finish = ("start", ""), ("finish", "")
    for payment in payments:
        identity = str(payment["payment_id"])
        node = ("payment", identity)
        edge(start, node, int(available[identity] * 100))
        for limit in payment.get("funding_limits", []):
            settlement = str(limit["settlement_id"])
            if settlement not in credits:
                raise ValueError("原款包含非本次所选批次的资金分摊")
            edge(node, ("batch", settlement), int(Decimal(limit["amount"]) * 100))
    for settlement, amount in sorted(credits.items()):
        edge(("batch", settlement), finish, amount)
    budget = sum(credits.values()) if target is None else int(target * 100)
    sent = 0
    while sent < budget:
        previous, pending = {start: None}, deque([start])
        while pending and finish not in previous:
            left = pending.popleft()
            for right in adjacent[left]:
                if right not in previous and capacity[left, right] > 0:
                    previous[right] = left
                    pending.append(right)
        if finish not in previous:
            break
        amount, right = budget - sent, finish
        while previous[right] is not None:
            left = previous[right]
            amount = min(amount, capacity[left, right])
            right = left
        right = finish
        while previous[right] is not None:
            left = previous[right]
            capacity[left, right] -= amount
            capacity[right, left] += amount
            right = left
        sent += amount
    allocations = {}
    for payment in payments:
        identity, funding = str(payment["payment_id"]), []
        for settlement in sorted(credits):
            value = capacity.get((("batch", settlement), ("payment", identity)), 0)
            if value:
                funding.append({"settlement_id": int(settlement), "amount": f"{Decimal(value)/100:.2f}"})
        allocations[identity] = {"amount": sum((Decimal(entry["amount"]) for entry in funding), Decimal(0)), "funding": funding}
    return Decimal(sent) / 100, allocations
