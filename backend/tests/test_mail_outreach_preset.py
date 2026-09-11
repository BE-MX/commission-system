"""preset 提示词与 SKILL.md 方法源的防漂移断言。

mail_outreach_generate 提示词以 .agents/skills/ark-email-outreach/SKILL.md 为唯一
方法源；两边必须同时出现关键门禁标记，任一边漂移都会在这里暴露。
"""

from pathlib import Path

from app.bootstrap.seed_ai import _MAIL_OUTREACH_SYSTEM_PROMPT

SKILL_MD = (
    Path(__file__).resolve().parents[2]
    / ".agents" / "skills" / "ark-email-outreach" / "SKILL.md"
)

# 两边真实共有的门禁标记（prompt 为中文、SKILL.md 为英文，只取字面共有的）
_SHARED_GATE_MARKERS = ("NOT READY TO SEND", "ready")
# preset 侧输出契约键（SKILL.md 不要求字面出现，防的是 prompt 自身漂移）
_PROMPT_ONLY_MARKERS = ("claims", "meaning_summary", "risk_flags", "missing_requirements")
# SKILL.md 侧方法源锚点
_SKILL_ONLY_MARKERS = ("evidence ledger", "allowed wording")


def test_skill_md_exists():
    assert SKILL_MD.is_file(), f"SKILL.md 不存在：{SKILL_MD}"


def test_shared_gate_markers_present_on_both_sides():
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    for marker in _SHARED_GATE_MARKERS:
        assert marker in _MAIL_OUTREACH_SYSTEM_PROMPT, f"preset 缺少 {marker}"
        assert marker in skill_text, f"SKILL.md 缺少 {marker}"


def test_prompt_keeps_output_contract_keys():
    for marker in _PROMPT_ONLY_MARKERS:
        assert marker in _MAIL_OUTREACH_SYSTEM_PROMPT, f"preset 缺少输出契约键 {marker}"


def test_skill_keeps_method_anchors():
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    for marker in _SKILL_ONLY_MARKERS:
        assert marker in skill_text, f"SKILL.md 缺少方法锚点 {marker}"
