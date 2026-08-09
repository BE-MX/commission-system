import pytest

from app.design_image.multi_output_intent import (
    STANDARD_ANGLES,
    build_composite_prompt,
    build_output_prompt,
    classify_multi_output_intent,
)


@pytest.mark.parametrize(
    ("prompt", "mode", "count", "labels"),
    [
        ("请生成3个角度的人像图", "clarify", 3, ("正面", "左侧 45°", "右侧 45°")),
        ("把正面侧面背面放在一张三视图里", "composite", 3, ("正面", "侧面", "背面")),
        ("分别生成三张：正面、左侧、右侧", "separate", 3, ("正面", "左侧", "右侧")),
        ("生成两个不同版本", "clarify", 2, ("独立变体 1/2", "独立变体 2/2")),
        ("生成1024×1024图片，参考图2", "single", 1, ()),
        ("生成5个角度", "reject", 5, ()),
        ("在同一张图里生成4个视角", "composite", 4, STANDARD_ANGLES[4]),
        ("分开生成四张效果图", "separate", 4, ("独立变体 1/4", "独立变体 2/4", "独立变体 3/4", "独立变体 4/4")),
        ("正面和背面各生成一张", "separate", 2, ("正面", "背面")),
        ("生成正面、左侧和右侧三个角度", "clarify", 3, ("正面", "左侧", "右侧")),
        ("生成3张人像图", "separate", 3, ("独立变体 1/3", "独立变体 2/3", "独立变体 3/3")),
        ("生成两个方向的人像", "clarify", 2, STANDARD_ANGLES[2]),
        ("生成三款设计", "clarify", 3, ("独立变体 1/3", "独立变体 2/3", "独立变体 3/3")),
        ("生成三张独立图片", "separate", 3, ("独立变体 1/3", "独立变体 2/3", "独立变体 3/3")),
        ("将四个视角排版展示", "composite", 4, STANDARD_ANGLES[4]),
        ("分别生成3张：正面、左侧30°、右侧60度", "separate", 3, ("正面", "左侧 30°", "右侧 60°")),
        ("生成三视图", "composite", 3, STANDARD_ANGLES[3]),
        ("生成四视图", "composite", 4, STANDARD_ANGLES[4]),
        ("分别生成3张：正面", "clarify", 3, STANDARD_ANGLES[3]),
        ("生成3种角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("生成三种角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("用2张高清产品参考图生成3个角度的人像", "clarify", 3, STANDARD_ANGLES[3]),
        ("使用2张参考图，请生成3个角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("参考2张图生成3个角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("参考图共2张，生成3个角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("参考图有2张，生成3个角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("参考图是2张，生成3个角度", "clarify", 3, STANDARD_ANGLES[3]),
        ("用3个角度展示这个人像", "clarify", 3, STANDARD_ANGLES[3]),
        ("采用3种方案生成海报", "clarify", 3, ("独立变体 1/3", "独立变体 2/3", "独立变体 3/3")),
        ("生成3张参考图", "separate", 3, ("独立变体 1/3", "独立变体 2/3", "独立变体 3/3")),
    ],
)
def test_classify_multi_output_intent(prompt, mode, count, labels):
    intent = classify_multi_output_intent(prompt)

    assert (intent.mode, intent.count, intent.labels) == (mode, count, labels)


@pytest.mark.parametrize(
    "prompt",
    [
        "人物年龄3岁",
        "使用参考图2",
        "尺寸1024×1024",
        "使用3种颜色搭配",
        "把亮度调到2档",
        "只生成一张产品图",
        "使用3张参考图生成产品主图",
        "上传2张素材图后生成海报",
        "使用3张高清参考图生成产品主图",
        "上传2张产品参考图后生成海报",
        "用2张原始素材图生成一张海报",
        "正面印Logo，背面印说明，生成一张包装盒效果图",
        "保留衣服正面和背面的图案",
        "分别在正面和背面添加logo，生成一张包装效果图",
        "突出3张参考图中的产品特点",
        "选出3张参考图里最好的元素",
        "取出3张素材图的背景色",
    ],
)
def test_non_output_numbers_remain_single(prompt):
    intent = classify_multi_output_intent(prompt)

    assert (intent.mode, intent.count, intent.labels) == ("single", 1, ())


def test_named_angle_count_mismatch_requires_clarification_with_standard_labels():
    intent = classify_multi_output_intent("分别生成3张：正面、背面")

    assert (intent.mode, intent.count, intent.labels) == (
        "clarify",
        3,
        STANDARD_ANGLES[3],
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (2, ("正面", "侧面 45°")),
        (3, ("正面", "左侧 45°", "右侧 45°")),
        (4, ("正面", "左侧 45°", "右侧 45°", "背面")),
    ],
)
def test_standard_angle_labels_are_stable(count, expected):
    assert STANDARD_ANGLES[count] == expected


def test_build_output_prompt_preserves_source_and_locks_one_output_label():
    source = "生成一组棚拍人像，保持人物身份"

    prompt = build_output_prompt(source, "左侧 45°")

    assert prompt.startswith(source)
    assert "左侧 45°" in prompt
    assert "仅生成这一张独立图片" in prompt
    assert "不得拼图" in prompt


def test_build_output_prompt_supports_generic_variant_labels():
    prompt = build_output_prompt("生成两个不同版本", "独立变体 2/2")

    assert "独立变体 2/2" in prompt
    assert "仅生成这一张独立图片" in prompt
    assert "与同组其他结果有可见差异" in prompt


def test_build_composite_prompt_preserves_source_and_lists_every_label():
    source = "生成三角度人物展示"
    labels = ("正面", "左侧 45°", "右侧 45°")

    prompt = build_composite_prompt(source, labels)

    assert prompt.startswith(source)
    assert all(label in prompt for label in labels)
    assert "同一张画布" in prompt
    assert "不得拆分为多张图片" in prompt


def test_build_angle_output_prompt_locks_reference_consistency():
    prompt = build_output_prompt("生成三角度人物展示", "正面")

    assert "人物身份、服装、发型、背景" in prompt
    assert "参考图一致" in prompt
