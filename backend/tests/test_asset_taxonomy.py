"""素材标签体系 v2：映射一致性 / 色号规范化 / 色系推导 / 单选校验 / 下载命名"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.asset.taxonomy_def import TAXONOMY_V2, iter_values
from scripts.tag_taxonomy.mapping_def import MAPPING, normalize_color
from scripts.tag_taxonomy.retag import derive_family


def _taxonomy_values() -> dict[str, set[str]]:
    return {d["name"]: {v["value"] for _, v in iter_values(d)} for d in TAXONOMY_V2}


# ── 映射与体系定义的一致性（漂移即红） ───────────────────

def test_mapping_targets_exist_in_taxonomy():
    values = _taxonomy_values()
    missing = []
    for (old_dim, old_val), targets in MAPPING.items():
        for dim_name, val, _p in targets:
            if val not in values.get(dim_name, set()):
                missing.append((old_dim, old_val, dim_name, val))
    assert missing == [], f"映射目标在 taxonomy 定义中不存在: {missing}"


def test_single_select_dims_have_no_same_priority_dual_targets():
    """同一个旧值映射到同一单选维度的多个值时，priority 必须能分出唯一胜者。"""
    single_dims = {d["name"] for d in TAXONOMY_V2 if d["is_single_select"]}
    for (old_dim, old_val), targets in MAPPING.items():
        by_dim: dict[str, list[int]] = {}
        for dim_name, val, p in targets:
            if dim_name in single_dims:
                by_dim.setdefault(dim_name, []).append(p)
        for dim_name, prios in by_dim.items():
            top = max(prios)
            assert prios.count(top) == 1, (
                f"旧值 ({old_dim},{old_val}) 在单选维度 {dim_name} 有同优先级多目标")


def test_content_type_parents_all_valid():
    values = _taxonomy_values()
    type_def = next(d for d in TAXONOMY_V2 if d["name"] == "content_type")
    for _, v in iter_values(type_def):
        assert v["parent"] in values["content_category"], f"{v['value']} 的父级无效"


def test_product_type_family_parents_valid():
    ptype = next(d for d in TAXONOMY_V2 if d["name"] == "product_type")
    own = {v["value"] for _, v in iter_values(ptype)}
    for _, v in iter_values(ptype):
        if v["parent"]:
            assert v["parent"] in own, f"{v['value']} 的产品族 {v['parent']} 不存在"


# ── 色号规范化 ───────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("#P1B--2B", [("color_code", "#P1B-2B", 5)]),
    ("#4TP18--22", [("color_code", "#4TP18-22", 5)]),
    ("#5ATP18B 62", [("color_code", "#5ATP18B-62", 5)]),
    ("#M9A-60 (8比2)", [("color_code", "#M9A-60(8:2)", 5)]),
    ("#M2-60（混色比例2：8）", [("color_code", "#M2-60(2:8)", 5)]),
    ("#Cookie cream", [("color_code", "#Cookies Cream", 5)]),
    ("#pink", [("color_code", "#Pink", 5)]),
    ("#1B", [("color_code", "#1B", 5)]),
])
def test_normalize_color_formats(raw, expected):
    assert normalize_color(raw) == expected


def test_normalize_color_product_prefix_split():
    out = normalize_color("半片PU卡子发-#2")
    assert ("product_type", "半片PU卡子发", 5) in out
    assert ("color_code", "#2", 5) in out


def test_normalize_color_combo_split():
    out = normalize_color("#4TP8-18+2TP2-8")
    codes = [v for d, v, _p in out if d == "color_code"]
    assert codes == ["#4TP8-18", "#2TP2-8"]


# ── 色系推导 ─────────────────────────────────────────────

@pytest.mark.parametrize("code,family", [
    ("#1", "黑色系"),
    ("#1B", "黑色系"),
    ("#4", "棕色系"),
    ("#613", "金色系"),
    ("#33", "红色系"),
    ("#Pink", "时尚色"),
    ("#P1B-2B", "挑染"),
    ("#4T60", "渐变"),
    ("#1BT6", "渐变"),
    ("#5ATP18B-62", "双段渐变"),
    ("#M9A-60(8:2)", "混色"),
    ("#Cookies Cream", "金色系"),
])
def test_derive_family(code, family):
    assert derive_family(code) == family


# ── 单选校验（DB） ───────────────────────────────────────

def _make_dims(db):
    from app.asset.models import TagDimension, TagValue

    single = TagDimension(name="tx_cat", label="测试大类", is_single_select=1, is_system=1)
    multi = TagDimension(name="tx_prod", label="测试产品", is_single_select=0, is_system=1)
    db.add_all([single, multi])
    db.flush()
    vals = [TagValue(dimension_id=single.id, value=f"S{i}") for i in range(2)]
    vals += [TagValue(dimension_id=multi.id, value=f"M{i}") for i in range(2)]
    db.add_all(vals)
    db.flush()
    return single, multi, vals


def test_single_select_violation_raises(db):
    from app.asset.asset_service import SingleSelectViolation, _validate_single_select
    from app.asset.schemas import AssetTagItem

    single, multi, vals = _make_dims(db)
    with pytest.raises(SingleSelectViolation):
        _validate_single_select(db, [
            AssetTagItem(dimension_id=single.id, tag_value_ids=[vals[0].id, vals[1].id]),
        ])
    # 多选维度多值合法；单选维度单值合法
    _validate_single_select(db, [
        AssetTagItem(dimension_id=multi.id, tag_value_ids=[vals[2].id, vals[3].id]),
        AssetTagItem(dimension_id=single.id, tag_value_ids=[vals[0].id]),
    ])


# ── 下载动态命名 ─────────────────────────────────────────

class _StubDim:
    def __init__(self, name, is_visible=1):
        self.name = name
        self.is_visible = is_visible


class _StubTag:
    def __init__(self, dim_name, value, parent_value_id=None, is_visible=1):
        self.dimension = _StubDim(dim_name, is_visible)
        self.value = value
        self.parent_value_id = parent_value_id


class _StubAsset:
    file_name = "048A9972.jpg"

    def __init__(self, tags):
        self.tags = tags


def test_build_download_filename_semantic():
    from app.asset.asset_service import build_download_filename

    asset = _StubAsset([
        _StubTag("product_type", "发帘类"),               # 族级值应被跳过
        _StubTag("product_type", "天才发帘", parent_value_id=1),
        _StubTag("color_code", "#8TP8-18"),
        _StubTag("shoot_style", "白底图"),
    ])
    assert build_download_filename(asset) == "天才发帘_#8TP8-18_白底图_048A9972.jpg"


def test_build_download_filename_fallback_original():
    from app.asset.asset_service import build_download_filename

    assert build_download_filename(_StubAsset([])) == "048A9972.jpg"


# ── folder_upload 合并判定（可见维度子集语义） ────────────

def test_tags_match_subset_ignores_hidden_and_managed():
    from app.asset.folder_upload_service import _tags_match

    comparable = {1, 2}          # 可见非托管维度
    existing = {(1, 10), (2, 20), (9, 90), (8, 80)}   # 9=隐藏新体系维度 8=托管色系
    # 目标只含路径映射出的可见标签 → 重打标追加的隐藏行不阻碍合并
    assert _tags_match(existing, {(1, 10), (2, 20)}, comparable) is True
    # 子集也合并（文件夹信息少于素材已有标签）
    assert _tags_match(existing, {(1, 10)}, comparable) is True
    # 可比较维度上有不一致 → 不合并
    assert _tags_match(existing, {(1, 11)}, comparable) is False
    # 目标全在不可比较维度 → 视为无标签，不合并
    assert _tags_match(existing, {(9, 90)}, comparable) is False
    assert _tags_match(existing, set(), comparable) is False


# ── MCP 权限过滤 ─────────────────────────────────────────

class _StubPerm:
    def __init__(self, group="all", allow_preview=1, users=None):
        self.permission_group = group
        self.allow_preview = allow_preview
        self.specified_user_ids = users


class _StubPermAsset:
    def __init__(self, perm):
        self.permissions = perm


def _user(sub="7", roles=(), perms=()):
    return {"sub": sub, "roles": list(roles), "permissions": list(perms)}


def test_mcp_permission_visible_rules():
    from app.mcp.asset_tools import _permission_visible

    # 无权限记录 / all 分组 → 可见
    assert _permission_visible(_StubPermAsset(None), _user())
    assert _permission_visible(_StubPermAsset(_StubPerm("all")), _user())
    # allow_preview=0 → 一律不可见（含 super_admin 也不放行预览关闭的）
    assert not _permission_visible(_StubPermAsset(_StubPerm("all", allow_preview=0)), _user(roles=["super_admin"]))
    # specific：本人可见，他人不可见
    assert _permission_visible(_StubPermAsset(_StubPerm("specific", users=[7])), _user(sub="7"))
    assert not _permission_visible(_StubPermAsset(_StubPerm("specific", users=[8])), _user(sub="7"))
    # design_dept/sales：普通用户收紧不可见，super_admin / asset:admin 可见
    assert not _permission_visible(_StubPermAsset(_StubPerm("design_dept")), _user())
    assert _permission_visible(_StubPermAsset(_StubPerm("design_dept")), _user(roles=["super_admin"]))
    assert _permission_visible(_StubPermAsset(_StubPerm("sales")), _user(perms=["asset:admin"]))


# ── 色系常态同步 ─────────────────────────────────────────

def test_sync_color_family_derives_and_overwrites(db):
    from app.asset.color_rules import sync_color_family
    from app.asset.models import Asset, TagDimension, TagValue, asset_tag_association as ata

    code_dim = TagDimension(name="color_code", label="色号", is_system=1)
    fam_dim = TagDimension(name="color_family", label="色系", is_system=1, is_managed=1)
    db.add_all([code_dim, fam_dim])
    db.flush()
    c1 = TagValue(dimension_id=code_dim.id, value="#1B")
    c2 = TagValue(dimension_id=code_dim.id, value="#5ATP18B-62")
    fams = [TagValue(dimension_id=fam_dim.id, value=v)
            for v in ["黑色系", "双段渐变", "渐变"]]
    db.add_all([c1, c2] + fams)
    db.flush()
    asset = Asset(file_name="x.jpg", file_type="image", file_format="jpg",
                  storage_path="t/x.jpg", uploader_id=1)
    db.add(asset)
    db.flush()
    db.execute(ata.insert().values(asset_id=asset.id, version_id=None,
                                   dimension_id=code_dim.id, tag_value_id=c1.id))
    db.execute(ata.insert().values(asset_id=asset.id, version_id=None,
                                   dimension_id=code_dim.id, tag_value_id=c2.id))

    sync_color_family(db, asset.id, None)
    rows = db.execute(ata.select().where(ata.c.dimension_id == fam_dim.id)).fetchall()
    got = {r.tag_value_id for r in rows}
    expect = {v.id for v in fams if v.value in ("黑色系", "双段渐变")}
    assert got == expect

    # 色号变化后重算覆盖旧色系
    db.execute(ata.delete().where(ata.c.tag_value_id == c2.id))
    sync_color_family(db, asset.id, None)
    rows = db.execute(ata.select().where(ata.c.dimension_id == fam_dim.id)).fetchall()
    assert {r.tag_value_id for r in rows} == {fams[0].id}
