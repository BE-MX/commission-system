"""展会门店配额服务测试。"""

import threading
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkUser
from app.expo.models import ExpoStore
from app.expo.quota_service import (
    InsufficientQuota,
    deduct_quota,
    get_quota,
    list_quota_records,
    recharge_quota,
)
from app.expo.store_service import StoreNotFound


def _make_user(db, username="u1"):
    user = ArkUser(
        username=username,
        password_hash="x",
        real_name=username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_store(db, total_quota=0, used_quota=0):
    store = ExpoStore(
        name="测试门店",
        code=f"t{uuid.uuid4().hex[:8]}",
        total_quota=total_quota,
        used_quota=used_quota,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


class TestGetQuota:
    def test_returns_snapshot(self, db):
        store = _make_store(db, total_quota=100, used_quota=30)
        snapshot = get_quota(db, store.id)
        assert snapshot == {
            "store_id": store.id,
            "total_quota": 100,
            "used_quota": 30,
            "remaining": 70,
        }

    def test_store_not_found(self, db):
        with pytest.raises(StoreNotFound):
            get_quota(db, 999999)


class TestRechargeQuota:
    def test_increases_total_and_balance(self, db):
        user = _make_user(db)
        store = _make_store(db, total_quota=100, used_quota=30)
        record = recharge_quota(
            db,
            store_id=store.id,
            amount=50,
            operator_user_id=user.id,
            remark="测试充值",
        )
        assert record.type == "recharge"
        assert record.amount == 50
        assert record.balance_before == 70
        assert record.balance_after == 120
        assert record.remark == "测试充值"

        snapshot = get_quota(db, store.id)
        assert snapshot == {
            "store_id": store.id,
            "total_quota": 150,
            "used_quota": 30,
            "remaining": 120,
        }

    def test_rejects_non_positive_amount(self, db):
        user = _make_user(db)
        store = _make_store(db)
        with pytest.raises(ValueError, match="正整数"):
            recharge_quota(db, store_id=store.id, amount=0, operator_user_id=user.id)
        with pytest.raises(ValueError, match="正整数"):
            recharge_quota(db, store_id=store.id, amount=-10, operator_user_id=user.id)


class TestDeductQuota:
    def test_increases_used_and_writes_negative_amount(self, db):
        user = _make_user(db)
        store = _make_store(db, total_quota=100, used_quota=30)
        record = deduct_quota(
            db,
            store_id=store.id,
            amount=20,
            operator_user_id=user.id,
            related_id=1,
            related_type="session",
            remark="测试扣减",
        )
        assert record.type == "deduct"
        assert record.amount == -20
        assert record.balance_before == 70
        assert record.balance_after == 50
        assert record.related_id == 1
        assert record.related_type == "session"
        assert record.remark == "测试扣减"

        snapshot = get_quota(db, store.id)
        assert snapshot == {
            "store_id": store.id,
            "total_quota": 100,
            "used_quota": 50,
            "remaining": 50,
        }

    def test_rejects_over_deduction(self, db):
        user = _make_user(db)
        store = _make_store(db, total_quota=100, used_quota=90)
        with pytest.raises(InsufficientQuota):
            deduct_quota(db, store_id=store.id, amount=20, operator_user_id=user.id)

        snapshot = get_quota(db, store.id)
        assert snapshot == {
            "store_id": store.id,
            "total_quota": 100,
            "used_quota": 90,
            "remaining": 10,
        }

    def test_rejects_non_positive_amount(self, db):
        user = _make_user(db)
        store = _make_store(db, total_quota=100)
        with pytest.raises(ValueError, match="正整数"):
            deduct_quota(db, store_id=store.id, amount=0, operator_user_id=user.id)


class TestListQuotaRecords:
    def test_pagination_and_type_filter(self, db):
        user = _make_user(db)
        store = _make_store(db, total_quota=100)
        recharge_quota(db, store_id=store.id, amount=50, operator_user_id=user.id)
        deduct_quota(db, store_id=store.id, amount=10, operator_user_id=user.id)
        deduct_quota(db, store_id=store.id, amount=5, operator_user_id=user.id)
        db.commit()

        rows, total = list_quota_records(db, store.id, limit=10, offset=0)
        assert total == 3
        assert len(rows) == 3
        assert {r.amount for r in rows} == {-5, -10, 50}
        assert rows[0].amount == -5  # 最后一条 deduct 最新的排在最前

        rows, total = list_quota_records(db, store.id, type_="deduct", limit=10)
        assert total == 2
        assert all(r.type == "deduct" for r in rows)

        rows, total = list_quota_records(db, store.id, limit=2, offset=0)
        assert total == 3
        assert len(rows) == 2

    def test_rejects_invalid_type(self, db):
        store = _make_store(db)
        with pytest.raises(ValueError, match="type_"):
            list_quota_records(db, store.id, type_="consume")


class TestQuotaIntegrity:
    def test_recharge_flush_failure_rolls_back_and_raises_clean_value_error(self, db, monkeypatch):
        """模拟 flush 时触发 IntegrityError，验证服务会 rollback 并抛干净 ValueError。"""
        user = _make_user(db)
        store = _make_store(db)
        user_id = user.id
        store_id = store.id

        def _boom():
            raise IntegrityError("stmt", "params", Exception("fk violation"))

        monkeypatch.setattr(db, "flush", _boom)
        with db.no_autoflush:
            with pytest.raises(ValueError, match="充值失败"):
                recharge_quota(
                    db,
                    store_id=store_id,
                    amount=10,
                    operator_user_id=user_id,
                )
            snapshot = get_quota(db, store_id)
        assert snapshot == {
            "store_id": store_id,
            "total_quota": 0,
            "used_quota": 0,
            "remaining": 0,
        }

    def test_deduct_flush_failure_rolls_back(self, db, monkeypatch):
        user = _make_user(db)
        store = _make_store(db, total_quota=100)
        user_id = user.id
        store_id = store.id

        def _boom():
            raise IntegrityError("stmt", "params", Exception("fk violation"))

        monkeypatch.setattr(db, "flush", _boom)
        with db.no_autoflush:
            with pytest.raises(ValueError, match="扣减失败"):
                deduct_quota(
                    db,
                    store_id=store_id,
                    amount=10,
                    operator_user_id=user_id,
                )
            snapshot = get_quota(db, store_id)
        assert snapshot == {
            "store_id": store_id,
            "total_quota": 100,
            "used_quota": 0,
            "remaining": 100,
        }

    def test_deduct_invalid_store_raises_store_not_found(self, db):
        user = _make_user(db)
        with pytest.raises(StoreNotFound):
            deduct_quota(db, store_id=999999, amount=10, operator_user_id=user.id)

    def test_recharge_invalid_store_raises_store_not_found(self, db):
        user = _make_user(db)
        with pytest.raises(StoreNotFound):
            recharge_quota(db, store_id=999999, amount=10, operator_user_id=user.id)


class TestConcurrentDeduct:
    def test_two_threads_cannot_over_deduct(self, db):
        """余额 2 时两个线程各扣 2，最终 used_quota 不允许超过 2。

        内存 SQLite + StaticPool 会让写实际串行，本测试重点是不超扣、无未预期异常；
        生产 MySQL 下 with_for_update() + populate_existing=True 保证同一时刻只有一笔成功。
        """
        user = _make_user(db)
        store = _make_store(db, total_quota=2, used_quota=0)
        store_id = store.id
        user_id = user.id
        db.commit()

        results = {"ok": 0, "errors": []}
        lock = threading.Lock()
        Session = sessionmaker(bind=db.get_bind())

        def worker():
            s = Session()
            try:
                deduct_quota(s, store_id=store_id, amount=2, operator_user_id=user_id)
                s.commit()
                with lock:
                    results["ok"] += 1
            except InsufficientQuota:
                s.rollback()
            except Exception as exc:
                with lock:
                    results["errors"].append(str(exc))
                s.rollback()
            finally:
                s.close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        db.expire_all()
        store = db.get(ExpoStore, store_id)
        assert store.used_quota <= 2, f"并发超扣: used_quota={store.used_quota}"
        assert not results["errors"], f"未预期异常: {results['errors']}"
