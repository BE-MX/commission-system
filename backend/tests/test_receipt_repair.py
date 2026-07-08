"""回款日期修复：匹配与解析纯逻辑测试。

不依赖业务库（跨库表），直接喂内存数据给纯函数 _match_row / parse_workbook。
"""

from contextlib import contextmanager
from datetime import date
from io import BytesIO

from openpyxl import Workbook

from app.invoice.receipt_repair_service import _match_row, apply_changes, parse_workbook


def _row(company, total, seq):
    return {"company": company, "order_total": total, "seq": seq, "n_receipts": len(seq)}


def _rec(ccid, no, amt, d, order_no="ON1"):
    return {"cash_collection_id": ccid, "cash_collection_no": no,
            "amount_usd": amt, "collection_date": d, "order_no": order_no}


# ---- 单笔 ----

def test_single_will_change():
    row = _row("Abbi white", 986.63, [(date(2026, 1, 9), 986.63)])
    name2ids = {"abbi white": {"C1"}}
    orders = {"C1": {"O1": 986.63}}
    receipts = {"O1": [_rec("R1", "14467", 950.0, date(2026, 1, 4))]}
    status, payload = _match_row(row, name2ids, orders, receipts)
    assert status == "will_change"
    assert len(payload["changes"]) == 1
    c = payload["changes"][0]
    assert c["cash_collection_id"] == "R1"
    assert c["old_date"] == "2026-01-04"
    assert c["new_date"] == "2026-01-09"


def test_single_already_ok():
    row = _row("Abbi white", 986.63, [(date(2026, 1, 9), 986.63)])
    name2ids = {"abbi white": {"C1"}}
    orders = {"C1": {"O1": 986.63}}
    receipts = {"O1": [_rec("R1", "14467", 950.0, date(2026, 1, 9))]}
    status, _ = _match_row(row, name2ids, orders, receipts)
    assert status == "already_ok"


def test_amount_mismatch_ignored_because_D_anchor():
    # 回款单金额 950 != 首笔 986.63，但用总额 D 锚点仍应命中
    row = _row("Abbi white", 986.63, [(date(2026, 1, 9), 986.63)])
    name2ids = {"abbi white": {"C1"}}
    orders = {"C1": {"O1": 986.63}}
    receipts = {"O1": [_rec("R1", "14467", 950.0, date(2026, 1, 4))]}
    status, _ = _match_row(row, name2ids, orders, receipts)
    assert status == "will_change"


# ---- 多笔：按回款单号顺序分配 ----

def test_multi_assigns_by_receipt_no_order():
    row = _row("Ruth French", 7260.20, [
        (date(2026, 1, 16), 2109.0),   # 首笔 -> A
        (date(2026, 3, 5), 5151.20),   # 次笔 -> H
    ])
    name2ids = {"ruth french": {"C1"}}
    orders = {"C1": {"O1": 7260.20}}
    # 故意乱序 + 首笔当前日期错误(1/12 应为 1/16)，次笔已正确
    receipts = {"O1": [
        _rec("R2", "14500", 5000.0, date(2026, 3, 5)),
        _rec("R1", "14468", 2000.0, date(2026, 1, 12)),
    ]}
    status, payload = _match_row(row, name2ids, orders, receipts)
    assert status == "will_change"
    # 只有首笔(单号更小的 R1)需要改
    assert [c["cash_collection_id"] for c in payload["changes"]] == ["R1"]
    assert payload["changes"][0]["new_date"] == "2026-01-16"


# ---- 无法匹配四类 ----

def test_company_not_found():
    row = _row("Kirsty Morley", 74.67, [(date(2026, 1, 9), 74.67)])
    status, _ = _match_row(row, {}, {}, {})
    assert status == "company_not_found"


def test_no_order_amount_match():
    row = _row("Ansley Rowell", 1526.59, [(date(2026, 1, 4), 1526.59)])
    name2ids = {"ansley rowell": {"C1"}}
    orders = {"C1": {"O1": 287.64}}  # 有客户，但没有总额=D 的订单
    status, _ = _match_row(row, name2ids, orders, {})
    assert status == "no_order_amount_match"


def test_multi_order_match():
    row = _row("Foo", 100.0, [(date(2026, 1, 1), 100.0)])
    name2ids = {"foo": {"C1"}}
    orders = {"C1": {"O1": 100.0, "O2": 100.0}}  # 两张同额订单
    receipts = {"O1": [_rec("R1", "1", 100.0, date(2026, 1, 1))]}
    status, payload = _match_row(row, name2ids, orders, receipts)
    assert status == "multi_order_match"
    assert payload["order_count"] == 2


def test_order_no_receipt():
    row = _row("Abbi white", 986.63, [(date(2026, 1, 9), 986.63)])
    name2ids = {"abbi white": {"C1"}}
    orders = {"C1": {"O1": 986.63}}
    status, _ = _match_row(row, name2ids, orders, {})  # 订单在，回款单不在
    assert status == "order_no_receipt"


def test_receipt_count_mismatch():
    row = _row("Foo", 100.0, [(date(2026, 1, 1), 60.0), (date(2026, 2, 1), 40.0)])  # excel 2 笔
    name2ids = {"foo": {"C1"}}
    orders = {"C1": {"O1": 100.0}}
    receipts = {"O1": [_rec("R1", "1", 100.0, date(2026, 1, 1))]}  # 库里 1 笔
    status, payload = _match_row(row, name2ids, orders, receipts)
    assert status == "receipt_count_mismatch"
    assert payload["db_count"] == 1 and payload["excel_count"] == 2


# ---- 解析 ----

def test_parse_workbook_reads_rows_and_receipts():
    wb = Workbook()
    ws = wb.active
    ws.append(["订单日期", "客户名", "国家", "总金额USD", "已回款金额", "实际运费", "手续费",
               "后续回款明细", None, "后续回款明细", None, "后续回款明细", None])
    ws.append([None] * 7 + ["回款日期", "回款金额", "回款日期", "回款金额", "回款日期", "回款金额"])
    # 单笔行
    ws.append([date(2026, 1, 9), "Abbi white", "美国", 986.63, 986.63, None, 49.33])
    # 多笔行：首笔 + 一笔后续(H/I)
    ws.append([date(2026, 1, 16), "Ruth French", "美国", 7260.20, 2109.0, None, 100,
               date(2026, 3, 5), 5151.20])
    buf = BytesIO()
    wb.save(buf)
    rows = parse_workbook(buf.getvalue())
    assert len(rows) == 2
    assert rows[0]["company"] == "Abbi white"
    assert rows[0]["order_total"] == 986.63
    assert rows[0]["n_receipts"] == 1
    assert rows[1]["n_receipts"] == 2
    assert rows[1]["seq"][0] == (date(2026, 1, 16), 2109.0)
    assert rows[1]["seq"][1] == (date(2026, 3, 5), 5151.20)


# ---- 写路径 apply_changes（FakeSession，不碰真实库）----

class _FakeResult:
    def __init__(self, row=None):
        self._row = row
    def mappings(self):
        return self
    def first(self):
        return self._row


class _FakeSession:
    """最小可用的 Session 替身：只支持 apply_changes 用到的调用。"""
    def __init__(self, receipts, fail_ids=None):
        self.receipts = receipts               # {ccid: {"collection_date","order_no","company_name"}}
        self.fail_ids = set(fail_ids or [])
        self.audits = []
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def begin_nested(self):
        yield  # 异常自然向外传播，由 apply_changes 的 try/except 兜住

    def execute(self, clause, params=None):
        sql = str(clause)
        params = params or {}
        if sql.strip().upper().startswith("SELECT"):
            rec = self.receipts.get(params["id"])
            return _FakeResult(rec)
        # UPDATE
        if params["id"] in self.fail_ids:
            raise RuntimeError("boom")
        self.receipts[params["id"]]["collection_date"] = params["d"]
        return _FakeResult()

    def add(self, obj):
        self.audits.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_apply_normal_updates_and_audits():
    db = _FakeSession({"R1": {"collection_date": date(2026, 1, 4), "order_no": "O", "company_name": "C"}})
    res = apply_changes(db, [{"cash_collection_id": "R1", "new_date": "2026-01-09"}], operator_id=7, source_file="f.xlsx")
    assert res["applied"] == 1 and res["failed"] == 0 and res["skipped"] == 0
    assert db.receipts["R1"]["collection_date"] == date(2026, 1, 9)
    assert len(db.audits) == 1
    assert db.audits[0].old_date == date(2026, 1, 4) and db.audits[0].new_date == date(2026, 1, 9)
    assert db.committed and not db.rolled_back


def test_apply_idempotent_skip_when_same_date():
    db = _FakeSession({"R1": {"collection_date": date(2026, 1, 9), "order_no": "O", "company_name": "C"}})
    res = apply_changes(db, [{"cash_collection_id": "R1", "new_date": "2026-01-09"}], operator_id=None)
    assert res["applied"] == 0 and res["skipped"] == 1
    assert not db.audits and db.rolled_back and not db.committed


def test_apply_skips_missing_receipt_and_bad_date():
    db = _FakeSession({"R1": {"collection_date": date(2026, 1, 4), "order_no": "O", "company_name": "C"}})
    res = apply_changes(db, [
        {"cash_collection_id": "NOPE", "new_date": "2026-01-09"},   # 不存在
        {"cash_collection_id": "R1", "new_date": "not-a-date"},     # 坏日期
        {"cash_collection_id": "", "new_date": "2026-01-09"},       # 空 id
    ], operator_id=None)
    assert res["applied"] == 0 and res["skipped"] == 3 and res["failed"] == 0


def test_apply_isolates_single_failure_and_commits_rest():
    db = _FakeSession(
        {"R1": {"collection_date": date(2026, 1, 4), "order_no": "O", "company_name": "C"},
         "R2": {"collection_date": date(2026, 1, 4), "order_no": "O", "company_name": "C"}},
        fail_ids=["R2"],
    )
    res = apply_changes(db, [
        {"cash_collection_id": "R1", "new_date": "2026-01-09"},
        {"cash_collection_id": "R2", "new_date": "2026-01-10"},
    ], operator_id=None)
    assert res["applied"] == 1 and res["failed"] == 1
    assert db.receipts["R1"]["collection_date"] == date(2026, 1, 9)  # 成功的照样落
    assert db.committed  # applied>0 → commit
    assert res["errors"]
