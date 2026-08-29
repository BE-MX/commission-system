# Expo Wig Prompt Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将15款发型反馈写入实时合成提示词，并通过有限面部适配、身份安全光影和头颈比例约束修复医生/高铁场景失真。

**Architecture:** 保持现有 `_build_prompt` 组装顺序和数据库结构不变，只替换 `ai_pipeline.py` 中已有提示词常量与两条场景描述；发型个性化要求继续由 `ark_expo_wigs.composite_prompt` 作为业务数据承载。所有行为先由 `test_expo_color_scene.py` 的失败断言锁定，再做最小实现，最后在单事务中更新并回读15款启用发型。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0、Pytest、MySQL

---

## 文件边界

- Modify: `backend/app/expo/ai_pipeline.py` — 合成身份锚、场景有限适配、光影范围、构图比例、医生与高铁场景。
- Modify: `backend/tests/test_expo_color_scene.py` — 提示词行为回归测试。
- Modify runtime data: `ark_expo_wigs.composite_prompt` — 15款启用发型的个性化提示词。
- Keep unchanged: `frontend/`、数据库 schema、Alembic、发型匹配与生成供应商。

### Task 1: 锁定面部唯一来源和有限场景适配

**Files:**
- Modify: `backend/tests/test_expo_color_scene.py`
- Modify: `backend/app/expo/ai_pipeline.py:770-784, 888-906, 1139-1143, 1182-1186`

- [ ] **Step 1: 写失败测试**

在构图测试前增加以下测试：

```python
def _tryon_scene_prompt(scene_key: str, variant: str = "real") -> str:
    scene = ai_pipeline.resolve_tryon_scene(scene_key)
    session = _session()
    wig = ExpoWig(model_no="LS-FACE", name="身份测试发", wig_description="short bob")
    row = ExpoResult(
        session_id=1,
        wig_id=1,
        scene_json={"key": scene_key, "label": scene["label"]},
    )
    return ai_pipeline._build_prompt(session, row, wig, variant=variant)[0]


class TestLimitedFaceAdaptation:
    def test_customer_photo_is_the_only_face_source(self):
        prompt = _tryon_scene_prompt("doctor")
        assert "sole visual source of truth for her face" in prompt
        assert "stable natural asymmetry, age traits and identifying skin marks" in prompt
        assert "wig references provide hair information only" in prompt

    def test_scene_is_composed_around_the_existing_gaze_first(self):
        prompt = _tryon_scene_prompt("hsrtravel")
        assert "compose the props and interaction around her existing gaze" in prompt
        assert "minimal coordinated adjustment" in prompt
        assert "same head-pose family" in prompt
        assert "same expression category and mouth-open state" in prompt

    def test_scene_no_longer_requires_free_face_reinterpretation(self):
        prompt = _tryon_scene_prompt("doctor")
        assert "Naturally adapt the background, outfit, pose, gesture and facial expression" not in prompt
        assert "locks identity, not expression" not in prompt
        assert "from frontal to profile or profile to frontal" in prompt

    @pytest.mark.parametrize("scene_key", ["doctor", "hsrtravel"])
    def test_identity_sensitive_scenes_do_not_prescribe_a_new_expression(self, scene_key):
        scene_prompt = ai_pipeline.resolve_tryon_scene(scene_key)["prompt"]
        banned = ("expression", "smile", "reassuring", "looking composed", "confident expression")
        assert all(word not in scene_prompt for word in banned)
        assert "compatible with her existing gaze direction" in scene_prompt
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
$py='D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe'
& $py -m pytest tests/test_expo_color_scene.py::TestLimitedFaceAdaptation -q
```

Expected: FAIL，缺少 `sole visual source of truth for her face`、`minimal coordinated adjustment` 等新规则。

- [ ] **Step 3: 最小修改合成身份锚**

在 `_COMPOSITE_TEMPLATE` 的原有保脸句后加入：

```python
" Treat the FIRST image as the sole visual source of truth for her face. Preserve its "
"exact geometry, stable natural asymmetry, age traits and identifying skin marks; do "
"not average, symmetrize, idealize or reinterpret them. The wig references provide hair "
"information only and must never influence the face."
```

将 `_TRYON_SCENE_CLAUSE` 的自由适配段替换为：

```python
_TRYON_SCENE_CLAUSE = (
    " Recreate the portrait in {scene}. Adapt the background, outfit, body pose and gesture "
    "to suit the scene, while preserving the FIRST image as the facial reference. Prefer her "
    "existing head angle, gaze direction and expression category, and first compose the props "
    "and interaction around her existing gaze. Only when the scene would otherwise look "
    "physically inconsistent, allow a minimal coordinated adjustment of head, eyes and "
    "micro-expression together, staying in the same head-pose family and the same expression "
    "category and mouth-open state. Never turn her from frontal to profile or profile to "
    "frontal, and never introduce a large head tilt, turn or pitch. Such adjustment may change "
    "only demeanor, never identity, facial geometry, age traits or skin marks. Keep the wig and "
    "hair color exactly as composited. Any other people may appear only as a soft, blurred, "
    "out-of-focus background presence - never in sharp focus, never with detailed faces or "
    "hands. The hair highlights and shadows must follow the scene's light direction, blending "
    "naturally with no cut-and-paste look. Shot like a candid 85mm documentary snapshot with "
    "shallow depth of field focused on the face and hair, natural and unposed."
) + _SUMMER_WARDROBE_CLAUSE
```

医生场景改为：

```python
{"key": "doctor", "label": "医生", "tagline": "专业信赖", "uniform": True,
 "prompt": ("a clean bright clinic consulting room, she stands professionally in a "
            "short-sleeve white coat with a stethoscope while reviewing a chart positioned "
            "compatible with her existing gaze direction, cool clinical daylight shaping "
            "her wig, white coat and room, blurred medical shelving and a faintly "
            "out-of-focus patient seated to the side")},
```

高铁场景改为：

```python
{"key": "hsrtravel", "label": "高铁出差", "tagline": "出差精致",
 "prompt": ("a high-speed train window seat, she sits in a natural business-travel pose "
            "with a laptop and tray positioned compatible with her existing gaze direction, "
            "bright window daylight shaping her wig, shoulders, clothing and seat, with a "
            "simple softly blurred sense of landscape motion outside")},
```

- [ ] **Step 4: 运行有限适配测试并确认通过**

Run: `& $py -m pytest tests/test_expo_color_scene.py::TestLimitedFaceAdaptation -q`

Expected: `4 passed`。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/expo/ai_pipeline.py backend/tests/test_expo_color_scene.py
git commit -m "fix(expo): bound scene face adaptation"
```

### Task 2: 保留场景光影但停止局部重画脸

**Files:**
- Modify: `backend/tests/test_expo_color_scene.py:392-421, 527-598`
- Modify: `backend/app/expo/ai_pipeline.py:966-1046`

- [ ] **Step 1: 将旧“必须重打脸光”测试改为身份安全光影测试**

把 `test_all_three_variants_light_the_face` 改为：

```python
def test_all_three_variants_limit_face_relighting(self):
    for name in ai_pipeline.PROMPT_VARIANTS:
        clause = ai_pipeline.resolve_prompt_variant(name)
        assert "uniform exposure and colour-temperature blend" in clause, name
        assert "do not add a new local key light, fill light or catchlight" in clause, name
        assert "Apply the scene's directional light fully to the wig, neck, clothing, body and background" in clause, name
        assert "distinct catchlights" not in clause, name
```

把 `TestLightingBase.test_present_on_every_output_path` 改为：

```python
def test_identity_safe_lighting_reaches_every_output_path(self):
    for name, prompt in _variant_prompts().items():
        assert "uniform exposure and colour-temperature blend" in prompt, name
        assert "never repaint the facial shadow pattern" in prompt, name
        assert "directional light fully to the wig, neck, clothing, body and background" in prompt, name
```

把几何锁的表情豁免断言改为：

```python
assert "facial anatomy stays immutable during any allowed micro-expression" in prompt
```

并在 `test_skin_handling_is_what_actually_differs` 中保留真实/柔光/美颜三档现有皮肤差异断言。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
& $py -m pytest tests/test_expo_color_scene.py::TestPromptVariantSwitch tests/test_expo_color_scene.py::TestLightingBase -q
```

Expected: FAIL，当前仍要求颧骨/眉弓塑形和强眼神光。

- [ ] **Step 3: 替换共用光影底座**

```python
_LIGHTING_BASE = (
    " Preserve the FIRST image's facial lighting pattern and visible facial skin as the visual "
    "anchor. Match the face to the scene only with a gentle, uniform exposure and "
    "colour-temperature blend; do not add a new local key light, fill light or catchlight on "
    "the face, and never repaint the facial shadow pattern around the cheekbones, brow, eyes, "
    "nose or mouth. Apply the scene's directional light fully to the wig, neck, clothing, body "
    "and background, including coherent highlights, contact shadows and colour. Her face keeps "
    "the exact geometry of the first image - the same face width, cheek contour and jawline, "
    "neither slimmer nor fuller. Facial anatomy stays immutable during any allowed "
    "micro-expression; light may blend the portrait, never reshape the face."
)
```

柔光差异改为只柔化面部锚以外的场景：

```python
"soft": (
    _LIGHTING_BASE
    + " Use a softer, more diffused scene light on the wig, clothing, body and background, "
    "lowering contrast outside the facial anchor while keeping the face limited to the "
    "uniform blend described above."
    + _SKIN_UNTOUCHED
),
```

美颜版删除 `Use a soft, flattering beauty light.`，改为 `Use a restrained beauty finish within the existing facial boundary.`；保留现有磨皮范围、磨皮后几何复锁和 `_HAIR_FIDELITY_GUARD`。

- [ ] **Step 4: 运行光影测试并确认通过**

Run: `& $py -m pytest tests/test_expo_color_scene.py::TestPromptVariantSwitch tests/test_expo_color_scene.py::TestLightingBase -q`

Expected: 相关测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/expo/ai_pipeline.py backend/tests/test_expo_color_scene.py
git commit -m "fix(expo): preserve faces during scene lighting"
```

### Task 3: 修复头大、脖子短和肩部压缩

**Files:**
- Modify: `backend/tests/test_expo_color_scene.py:354-373`
- Modify: `backend/app/expo/ai_pipeline.py:908-940`

- [ ] **Step 1: 将构图测试改成关系比例约束**

```python
def test_scene_swap_framing_preserves_head_neck_and_shoulders():
    session = _session()
    wig = ExpoWig(model_no="LS-9", name="胎毛波波", wig_description="airy bob")
    row = ExpoResult(session_id=1, wig_id=9,
                     scene_json={"key": "whitecollar", "label": "白领高管"})
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)

    assert "waist-up" in prompt
    assert "full shoulder span, upper chest and collarbone area" in prompt
    assert "original head scale and natural neck length" in prompt
    assert "visible space from jawline to neckline" in prompt
    assert "never raise the shoulders, shorten the neck" in prompt
    assert "one third of the frame height" not in prompt
    assert "no wide-angle facial distortion" in prompt
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `& $py -m pytest tests/test_expo_color_scene.py::test_scene_swap_framing_preserves_head_neck_and_shoulders -q`

Expected: FAIL，当前仍使用 `one third of the frame height`。

- [ ] **Step 3: 替换 `_FRAMING_CLAUSE` 的比例段**

保留腰上构图、完整发型、85mm、防广角畸变和背景融合，删除头占画面三分之一，写入：

```python
" Keep her full shoulder span, upper chest and collarbone area in frame: this is a waist-up "
"portrait, not a head-and-shoulders close-up. Preserve the FIRST image's original head scale "
"and natural neck length relative to her shoulders and torso, with natural visible space from "
"jawline to neckline. Never raise the shoulders, shorten the neck, enlarge the skull or let the "
"wig's volume change the body's proportions. The wig silhouette comes from its references, but "
"the customer's head, neck and shoulder proportions do not."
```

- [ ] **Step 4: 运行构图测试和完整展会提示词测试**

Run: `& $py -m pytest tests/test_expo_color_scene.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/expo/ai_pipeline.py backend/tests/test_expo_color_scene.py
git commit -m "fix(expo): preserve natural head and neck proportions"
```

### Task 4: 单事务更新15款发型补充提示词

**Data:**
- Modify: `ark_expo_wigs.composite_prompt`
- Keep unchanged: `9003 ·魅力卷`

- [ ] **Step 1: 在事务中校验目标并更新**

从含 `backend/.env` 的主工作区运行下面的 Python 事务。`expected` 必须与当前启用记录完全匹配；任一缺失、停用或名称变化都会抛错并回滚。

```python
from sqlalchemy import bindparam, text
from app.core.database import SessionLocal

prompts = {
    1: ("6010", "刘海为自然斜向的齐碎结构：左侧厚重堆积、右侧轻薄过渡；缩短鬓角并软化末端，鬓角和刘海均不能形成整齐水平切线。"),
    2: ("6010-B", "保持纯直发，禁止波纹、纹理卷或蓬松束状；刘海整体斜向但单根发丝有垂直下落感，边缘干净连续，不做碎刘海。"),
    3: ("35厘米长直发", "最终发尾到上胸位置，比当前结果向下延长约5厘米；底边自然轻微错落和渐薄，不能形成过齐的水平切线；发型贴合颅顶，不过度饱满和蓬松。"),
    4: ("8003", "两侧层次起点和外轮廓向下调整约1.5厘米，保留更低、更连贯的侧区重量，避免高层次台阶。"),
    5: ("完全挂耳波波", "两侧长度到耳垂以下约1厘米；刘海加长并保持正向，不能变成斜刘海；削薄两侧下部和发尾堆积，避免耳下区域过厚。"),
    6: ("9005纹理卷", "卷纹和走向比当前结果更清晰，但每束保持柔软自然；降低头顶高度和蓬松度；刘海适当加长，减少额头暴露。"),
    7: ("6010时尚款", "整体轮廓比标准6010更短、更贴合、更精练，重点收短耳周和后颈，保持轻盈而不膨大。"),
    8: ("一刀切", "发尾垂直笔直落下，禁止内扣或向脸侧弯曲；最终长度稳定在肩膀以下约2厘米。"),
    9: ("8001眉上刘海纹理", "保持现有长度和轮廓；纹理拆成细密、柔和、连续的小束，束间自然融合，避免僵硬、粗大、彼此分离的一撮一撮效果。"),
    11: ("果阳雪棕", "发型变化不得改变客户身份、年龄、脸型、五官比例和原有皮肤特征，禁止将人物老化、年轻化或替换为另一张脸。"),
    12: ("25厘米侧分直发", "保持侧分方向；额前刘海发根轻微抬起并带自然空气感，不贴额头；发梢位置保持在脖子以下。"),
    13: ("6201锡纸烫", "两侧、刘海和整体下缘较当前结果向下延长约1.5厘米；锡纸烫束条细、窄、密，整体更自然下垂，避免粗束和向外炸开。"),
    14: ("6307小清新波波", "刘海长度和疏密自然错落、松散柔和，避免均匀梳齿状；整体外轮廓再缩短一些，同时保留波波头形态。"),
    15: ("胎毛波波", "刘海按四六比例侧分；发量较多的一侧由短到长斜向过渡，不能形成齐刘海；胎毛只保留为贴近发际线的短细绒毛，不能延长成刘海。"),
    16: ("主持人纹理", "两侧、鬓角和刘海整体向下延长约1.5厘米；刘海下缘为自然松散的不规则锯齿轮廓，不能剪成水平齐线。"),
}

db = SessionLocal()
try:
    query = text(
        "SELECT id, name, is_active, composite_prompt FROM ark_expo_wigs "
        "WHERE id IN :ids FOR UPDATE"
    ).bindparams(bindparam("ids", expanding=True))
    rows = db.execute(query, {"ids": list(prompts)}).mappings().all()
    actual = {row["id"]: row for row in rows}
    if set(actual) != set(prompts):
        raise RuntimeError(f"发型ID不完整: expected={sorted(prompts)}, actual={sorted(actual)}")
    for wig_id, (expected_name, prompt) in prompts.items():
        row = actual[wig_id]
        if row["is_active"] != 1 or row["name"].strip() != expected_name:
            raise RuntimeError(f"发型校验失败: id={wig_id}, row={dict(row)}")
        db.execute(
            text("UPDATE ark_expo_wigs SET composite_prompt=:prompt WHERE id=:wig_id"),
            {"prompt": prompt, "wig_id": wig_id},
        )
    db.commit()
except Exception:
    db.rollback()
    raise
finally:
    db.close()
```

- [ ] **Step 2: 回读验证15款和魅力卷**

Run a read-only query asserting:

```python
assert all(actual[id]["composite_prompt"] == prompts[id][1] for id in prompts)
assert charm["id"] == 10
assert charm["name"].strip() == "9003 ·魅力卷"
assert charm["composite_prompt"] == "此发型合成时严格要求原始人物的脸型与五官不能做任何改动"
```

Expected: 15款全部精确匹配，魅力卷未改变。

### Task 5: 全量验证、提交计划并合并推送

**Files:**
- Create: `docs/superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md`

- [ ] **Step 1: 运行专项测试**

Run: `& $py -m pytest tests/test_expo_color_scene.py -q`

Expected: 全部通过。

- [ ] **Step 2: 运行完整后端测试**

Run from `backend/`: `& $py -m pytest -q`

Expected: 0 failures。

- [ ] **Step 3: 运行项目约定检查**

Run from repository root:

```powershell
& $py scripts/check_conventions.py --base (git merge-base main HEAD)
```

Expected: 无红项。

- [ ] **Step 4: 检查差异和提交实施计划**

```powershell
git diff --check
git status --short
git add docs/superpowers/plans/2026-08-29-expo-wig-prompt-fidelity.md
git commit -m "docs(expo): add prompt fidelity implementation plan"
```

- [ ] **Step 5: 推送功能分支、在主工作区合并并复验**

```powershell
git push
git -C D:\MyProgram\commission-system pull --ff-only origin main
git -C D:\MyProgram\commission-system merge --no-ff codex/expo-prompt-fidelity-20260829 -m "merge: improve expo try-on fidelity"
```

在主工作区使用同一专项测试命令复验，确认通过后执行：

```powershell
git -C D:\MyProgram\commission-system push origin main
```

- [ ] **Step 6: 清理已合并分支和工作区**

按仓库约定，主分支成功推送后删除本地与远端功能分支，并移除 `D:\MyProgram\commission-system-codex-expo-prompt-fidelity` worktree。删除前再次确认 worktree clean、分支已合并且远端 main 包含合并提交。
