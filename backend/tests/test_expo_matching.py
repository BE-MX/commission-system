"""展会试戴匹配引擎单元测试（纯函数，不依赖数据库）。"""

from types import SimpleNamespace

from app.expo import matching
from app.expo.script_service import check_forbidden

WEIGHTS = matching.DEFAULT_WEIGHTS


def make_wig(wig_id, series="classic", priority=0, **tags):
    return SimpleNamespace(
        id=wig_id,
        series=series,
        priority=priority,
        fit_tags=tags,
        selling_points=None,
        name=f"wig-{wig_id}",
    )


ANALYSIS = {
    "gender": "female",
    "age_range": "40-50",
    "face_shape": "round",
    "skin_tone": {"depth": "light", "undertone": "warm"},
    "temperament": "知性优雅",
}
REG = {"primary_need": "volume", "style_pref": "知性优雅"}


class TestScoreWig:
    def test_full_hit_scores_all_weights(self):
        wig = make_wig(
            1,
            gender="female",
            face_shapes=["round"],
            skin_depths=["light"],
            undertones=["warm"],
            needs=["volume"],
            styles=["知性优雅"],
            age_ranges=["35-55"],
        )
        score = matching.score_wig(wig, ANALYSIS, REG, WEIGHTS)
        assert score == sum(WEIGHTS.values())

    def test_no_tags_scores_zero(self):
        assert matching.score_wig(make_wig(1), ANALYSIS, REG, WEIGHTS) == 0

    def test_skin_tone_split_half(self):
        wig = make_wig(1, skin_depths=["light"])  # 只命中深浅，不命中冷暖
        assert matching.score_wig(wig, ANALYSIS, REG, WEIGHTS) == WEIGHTS["skin_tone"] / 2

    def test_style_single_hit_partial(self):
        # temperament 与 style_pref 相同且都命中 → 计 2 hits 满分
        wig = make_wig(1, styles=["知性优雅"])
        assert matching.score_wig(wig, ANALYSIS, REG, WEIGHTS) == WEIGHTS["style"]
        # 只命中 temperament（style_pref 不同）→ 0.6 折算
        reg = {**REG, "style_pref": "自然日常"}
        assert matching.score_wig(wig, ANALYSIS, reg, WEIGHTS) == WEIGHTS["style"] * 0.6

    def test_age_overlap(self):
        wig = make_wig(1, age_ranges=["45-60"])  # 与 40-50 有交集
        assert matching.score_wig(wig, ANALYSIS, REG, WEIGHTS) == WEIGHTS["age"]
        wig2 = make_wig(2, age_ranges=["20-30"])  # 无交集
        assert matching.score_wig(wig2, ANALYSIS, REG, WEIGHTS) == 0


class TestMatchWigs:
    def test_gender_hard_filter(self):
        wigs = [
            make_wig(1, gender="male", face_shapes=["round"]),
            make_wig(2, gender="female"),
        ]
        result = matching.match_wigs(wigs, ANALYSIS, REG)
        assert [r["wig_id"] for r in result] == [2]

    def test_ranking_by_score_then_priority(self):
        strong = make_wig(1, face_shapes=["round"], needs=["volume"])
        weak = make_wig(2, face_shapes=["round"])
        tied_low = make_wig(3, face_shapes=["round"], priority=0)
        tied_high = make_wig(4, face_shapes=["round"], priority=5)
        result = matching.match_wigs([tied_low, weak, strong, tied_high], ANALYSIS, REG)
        ids = [r["wig_id"] for r in result]
        assert ids[0] == 1               # 分数最高
        assert ids.index(4) < ids.index(3)  # 同分 priority 高者靠前

    def test_zhizhen_anchor_swaps_into_first_batch(self):
        # 4 个高分 classic + 1 个第 5 名的 zhizhen → zhizhen 应进第一批（第 3 位）
        classics = [
            make_wig(i, face_shapes=["round"], needs=["volume"], skin_depths=["light"], priority=10 - i)
            for i in range(1, 5)
        ]
        zhizhen = make_wig(9, series="zhizhen", face_shapes=["round"])
        result = matching.match_wigs([*classics, zhizhen], ANALYSIS, REG)
        first_batch = [r["wig_id"] for r in result[:3]]
        assert 9 in first_batch
        # 被换下的 classic 出现在后位，不丢失
        all_ids = [r["wig_id"] for r in result]
        assert sorted(all_ids) == [1, 2, 3, 4, 9]

    def test_zhizhen_already_in_top3_no_swap(self):
        zhizhen = make_wig(1, series="zhizhen", face_shapes=["round"], needs=["volume"])
        others = [make_wig(i, face_shapes=["round"]) for i in range(2, 6)]
        result = matching.match_wigs([zhizhen, *others], ANALYSIS, REG)
        assert result[0]["wig_id"] == 1

    def test_reason_is_positive_and_nonempty(self):
        wig = make_wig(1, face_shapes=["round"], undertones=["warm"])
        result = matching.match_wigs([wig], ANALYSIS, REG)
        reason = result[0]["reason"]
        assert reason
        assert "圆脸" in reason or "肤色" in reason

    def test_gender_all_filtered_falls_back_to_unfiltered(self):
        """性别过滤全灭（男顾客 × 全女款库）→ 降级不过滤，绝不返回 0 款（线上 session=5 实case）。"""
        wigs = [
            make_wig(1, gender="female", face_shapes=["round"]),
            make_wig(2, gender="female", styles=["知性优雅"]),
        ]
        analysis = {**ANALYSIS, "gender": "male"}
        result = matching.match_wigs(wigs, analysis, REG)
        assert sorted(r["wig_id"] for r in result) == [1, 2]
        assert result[0]["wig_id"] == 1  # 兜底后仍按分数排名（脸型命中者靠前）

    def test_gender_partial_match_no_fallback(self):
        """只要有任一款过滤存活，就不触发兜底（不给男顾客混推女款）。"""
        wigs = [
            make_wig(1, gender="female"),
            make_wig(2, gender="male"),
        ]
        analysis = {**ANALYSIS, "gender": "male"}
        result = matching.match_wigs(wigs, analysis, REG)
        assert [r["wig_id"] for r in result] == [2]

    def test_empty_library_returns_empty(self):
        assert matching.match_wigs([], ANALYSIS, REG) == []


def _wig(wig_id, must_recommend=0, series="classic", priority=0, **tags):
    w = make_wig(wig_id, series=series, priority=priority, **tags)
    w.must_recommend = must_recommend
    return w


class TestPriorityBoost:
    def test_boost_raises_score_and_rank(self):
        a = _wig(1, priority=0, face_shapes=["round"])    # base 30
        b = _wig(2, priority=20, face_shapes=["round"])   # 30 + min(20*0.2,6)=4 = 34
        res = matching.match_wigs([a, b], ANALYSIS, REG)
        assert res[0]["wig_id"] == 2
        assert res[0]["score"] == 34.0 and res[1]["score"] == 30.0

    def test_boost_capped(self):
        a = _wig(1, priority=1000, face_shapes=["round"])
        res = matching.match_wigs([a], ANALYSIS, REG)
        assert res[0]["score"] == 36.0  # 30 + cap 6

    def test_boost_does_not_cross_big_tier(self):
        """高 priority 低匹配款吃不掉与高匹配款的大分差（封顶保证不跨档）。"""
        high = _wig(1, priority=0, face_shapes=["round"], needs=["volume"])  # 30+25=55
        lowp = _wig(2, priority=1000, face_shapes=["round"])                 # 30+6=36
        res = matching.match_wigs([high, lowp], ANALYSIS, REG)
        assert res[0]["wig_id"] == 1

    def test_config_present(self):
        cfg = matching.load_config()
        assert cfg["priority_boost"]["unit"] > 0 and cfg["priority_boost"]["cap"] > 0


class TestMustRecommend:
    def test_guaranteed_in_top6_not_first(self):
        good = [_wig(i, face_shapes=["round"]) for i in range(1, 7)]  # 6 款 base 30
        must = _wig(99, must_recommend=1)                             # base 0 但必推
        res = matching.match_wigs(good + [must], ANALYSIS, REG)
        ids = [r["wig_id"] for r in res]
        assert 99 in ids[:6]   # 必推进前 6
        assert ids[0] != 99    # 不强占第一
        assert ids[6] != 99    # 被挤出的高分款落到第 7，不丢失

    def test_already_in_top6_untouched(self):
        wigs = [_wig(i, face_shapes=["round"]) for i in range(1, 7)]
        wigs.append(_wig(7, must_recommend=1, face_shapes=["round"]))  # 匹配也高，本就在前
        res = matching.match_wigs(wigs, ANALYSIS, REG)
        assert 7 in [r["wig_id"] for r in res[:6]]

    def test_still_gender_filtered(self):
        """性别硬过滤对必推款同样生效：不给女顾客强推男款。"""
        male_must = _wig(50, must_recommend=1, gender="male")
        female = _wig(1, gender="female", face_shapes=["round"])
        res = matching.match_wigs([male_must, female], ANALYSIS, REG)  # ANALYSIS gender=female
        ids = [r["wig_id"] for r in res]
        assert 50 not in ids
        assert 1 in ids


class TestForbiddenWords:
    def test_hit_detection(self):
        assert check_forbidden("这个很划算，性价比高") == ["划算", "性价比"]

    def test_clean_text_passes(self):
        assert check_forbidden("久戴如新，气质升级，对自己好一点") == []

    def test_seed_scripts_are_clean(self):
        from app.expo.script_service import _SEED
        for card in _SEED:
            assert check_forbidden(card["content"]) == [], f"种子话术卡命中禁用词: {card['title']}"
