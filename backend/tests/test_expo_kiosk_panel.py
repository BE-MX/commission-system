"""kiosk 销售面板（线索列表+话术查看，2026-07-13）服务层测试。

核心保障：共享屏最小暴露面——手机号脱敏、话术载荷不含 internal 发况与照片路径。
"""

from app.expo import service
from app.expo.models import ExpoCustomer, ExpoResult, ExpoSession, ExpoWig
from app.expo.schemas import CustomerRegister


def _customer(db, name="陈女士", phone="13812341234"):
    return service.register_customer(db, CustomerRegister(
        name=name, phone=phone, wechat_id="wx_secret",
        primary_need="volume", style_pref="知性优雅",
        consent=True, expo_code="2026-08-expo",
    ))


class TestMaskPhone:
    def test_standard_11_digit(self):
        assert service.mask_phone("13812341234") == "138****1234"

    def test_short_number(self):
        assert service.mask_phone("12345") == "1***"

    def test_empty_and_none(self):
        assert service.mask_phone("") == ""
        assert service.mask_phone(None) == ""


class TestKioskLeadSerializer:
    def test_masked_and_trimmed(self, db):
        c = _customer(db)
        rows, total = service.list_leads(db, page=1, page_size=10)
        assert total == 1
        lead = service.serialize_kiosk_lead(rows[0])
        assert lead["customer_id"] == c.id
        assert lead["phone_masked"] == "138****1234"
        # 共享屏最小暴露面：全量手机号/微信号/销售备注不出现在载荷里
        assert "phone" not in lead and "wechat_id" not in lead and "last_note" not in lead

    def test_keyword_search_hits_full_phone(self, db):
        _customer(db, name="王女士", phone="13987654321")
        rows, _ = service.list_leads(db, page=1, page_size=10, keyword="4321")
        assert len(rows) == 1 and rows[0]["name"] == "王女士"


class TestKioskStrategy:
    def test_missing_customer_returns_none(self, db):
        assert service.get_kiosk_strategy(db, 99999) is None

    def test_picks_latest_generated_strategy(self, db):
        c = _customer(db)
        strategy_old = {"opener": "旧话术", "followup": "", "objections": []}
        strategy_new = {"opener": "新话术", "followup": "跟进", "objections": [{"q": "q", "a": "a"}]}
        db.add(ExpoSession(customer_id=c.id, photo_path="p1.jpg", status="done",
                           strategy_json=strategy_old))
        db.add(ExpoSession(customer_id=c.id, photo_path="p2.jpg", status="done",
                           strategy_json=strategy_new))
        db.add(ExpoSession(customer_id=c.id, photo_path="p3.jpg", status="analyzed"))  # 最新但无话术
        db.commit()

        payload = service.get_kiosk_strategy(db, c.id)
        assert payload["strategy"] == strategy_new  # 最新一条「已生成」的话术
        assert payload["strategy_pending"] is False
        assert payload["customer"]["phone_masked"] == "138****1234"

    def test_pending_flag_while_generating(self, db):
        c = _customer(db)
        db.add(ExpoSession(customer_id=c.id, photo_path="p.jpg", status="generating"))
        db.commit()
        payload = service.get_kiosk_strategy(db, c.id)
        assert payload["strategy"] is None
        assert payload["strategy_pending"] is True

    def test_scene_session_never_pending(self, db):
        """scene 会话不生成话术：合成中也不许假显「话术生成中」空转轮询。"""
        c = _customer(db)
        db.add(ExpoSession(customer_id=c.id, photo_path="p.jpg", mode="scene", status="generating"))
        db.commit()
        payload = service.get_kiosk_strategy(db, c.id)
        assert payload["strategy_pending"] is False

    def test_strategy_extra_keys_whitelisted(self, db):
        """模型/回落路径夹带的多余键（如 fallback 标记）不出 kiosk 载荷。"""
        c = _customer(db)
        db.add(ExpoSession(customer_id=c.id, photo_path="p.jpg", status="done",
                           strategy_json={"opener": "o", "followup": "f", "objections": [],
                                          "fallback": True, "internal_note": "x"}))
        db.commit()
        payload = service.get_kiosk_strategy(db, c.id)
        assert set(payload["strategy"].keys()) == {"opener", "followup", "objections"}

    def test_mask_mid_length_number_heavy(self):
        """8~10 位座机/短号走重脱敏，不走留3+留4（只藏1~2位形同裸奔）。"""
        assert service.mask_phone("07551234") == "0***"
        assert service.mask_phone("075512345678") == "075****5678"

    def test_no_internal_or_photo_leakage(self, db):
        c = _customer(db)
        db.add(ExpoSession(
            customer_id=c.id, photo_path="private.jpg", status="done",
            analysis_json={"face_shape": "round", "internal": {"hair_volume": "稀疏"}},
            strategy_json={"opener": "o", "followup": "f", "objections": []},
        ))
        db.commit()
        payload = service.get_kiosk_strategy(db, c.id)
        flat = str(payload)
        assert "internal" not in flat and "稀疏" not in flat  # 发况判断永不出 kiosk
        assert "private.jpg" not in flat                      # 原始照片路径不出
        assert "wx_secret" not in flat                        # 微信号不出

    def test_tried_wigs_dedupe(self, db):
        c = _customer(db)
        wig = ExpoWig(model_no="LS-1", name="轻盈波波", series="classic")
        db.add(wig)
        db.flush()
        s = ExpoSession(customer_id=c.id, photo_path="p.jpg", status="done",
                        strategy_json={"opener": "o"})
        db.add(s)
        db.flush()
        db.add(ExpoResult(session_id=s.id, wig_id=wig.id, status="done"))
        db.add(ExpoResult(session_id=s.id, wig_id=wig.id, status="done"))  # 同款两张图
        db.commit()
        payload = service.get_kiosk_strategy(db, c.id)
        assert payload["tried_wigs"] == ["轻盈波波"]
