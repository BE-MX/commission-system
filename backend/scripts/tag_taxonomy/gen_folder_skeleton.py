"""按当前标签体系生成上传目录模板（空文件夹骨架）

用法（backend/ 目录下）：
    python scripts/tag_taxonomy/gen_folder_skeleton.py [输出根目录]

默认输出到桌面「素材上传目录模板」。文件夹名 = 标签库规范值（从 DB 实时读取，
含设计部后续在管理页新增的值），folder_upload 的路径匹配可 100% 命中。

结构（层级顺序不影响标签识别，仅为人整理习惯）：
    <年份>/<内容大类>/<内容子类>/[<产品类型>]/[<拍摄风格>]
    生产工艺/工艺流程记录 下铺工艺环节；营销设计/节日海报 下铺节日主题。
色号/纹理不进目录（组合爆炸），写在文件名里或上传后 AI 建议补。
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.database import SessionLocal
from app.asset.models import TagDimension, TagValue

README = """【素材上传目录模板 · 使用说明】

1. 把素材文件放进对应的最深层文件夹，然后在方舟平台「素材上传-文件夹上传」
   里选择整个「{year}」文件夹（或任意子文件夹）即可，系统按文件夹名自动打标签。

2. 文件夹名 = 标签，请勿改名（改名会导致标签识别失败进入人工确认）。
   用不到的文件夹可以整层删掉，不影响其他层识别。

3. 色号写在文件名里（如 #1B_正面.jpg、#8TP8-18_细节.mp4），
   上传时点「AI 建议标签」自动识别，或上传后手工补。
   纹理（直发/Body Wave/Curly...）同理。

4. 每年复制一份模板，把「{year}」改成新一年（如 2027年）即可继续用。

5. 出了新产品/新节日主题：先请管理员在「标签维度管理」页加标签值，
   再自建同名文件夹（名字必须一字不差）。

生成时间：{today}（标签值取自当时的标签库，后续新增值需自建文件夹）
"""


def _values(db, dim_name, with_parent=None):
    dim = db.query(TagDimension).filter(TagDimension.name == dim_name).first()
    if not dim:
        return []
    q = (db.query(TagValue)
         .filter(TagValue.dimension_id == dim.id, TagValue.is_active == 1)
         .order_by(TagValue.sort_order))
    vals = q.all()
    if with_parent is True:      # 仅有父级的（具体产品，排除族值与顶层杂项）
        vals = [v for v in vals if v.parent_value_id]
    return vals


def _safe(name: str) -> str:
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "-")
    return name.strip()


def main():
    year = f"{date.today().year}年"
    out_root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"), "Desktop", "素材上传目录模板")

    db = SessionLocal()
    content_dims = {d.name: d for d in db.query(TagDimension).all()}
    cat_dim = content_dims["content_category"]
    cats = _values(db, "content_category")
    types = _values(db, "content_type")
    products = [_safe(v.value) for v in _values(db, "product_type", with_parent=True)]
    styles = [_safe(v.value) for v in _values(db, "shoot_style")]
    steps = [_safe(v.value) for v in _values(db, "process_step")]
    themes = [_safe(v.value) for v in _values(db, "theme")]
    db.close()

    types_by_cat: dict[int, list] = {}
    for t in types:
        types_by_cat.setdefault(t.parent_value_id, []).append(t)

    # 哪些内容子类下值得按产品再分层
    PRODUCT_SPLIT_TYPES = {"产品展示", "细节图", "佩戴效果", "产品对比"}
    # 产品展示下再铺拍摄风格
    STYLE_SPLIT_TYPES = {"产品展示"}
    # 特殊铺层
    STEP_UNDER = "工艺流程记录"
    THEME_UNDER = "节日海报"

    made = 0

    def mk(*parts):
        nonlocal made
        p = os.path.join(out_root, year, *parts)
        os.makedirs(p, exist_ok=True)
        made += 1

    for cat in cats:
        cat_name = _safe(cat.value)
        subtypes = types_by_cat.get(cat.id, [])
        if not subtypes:
            mk(cat_name)
            continue
        for st in subtypes:
            st_name = _safe(st.value)
            if st.value in PRODUCT_SPLIT_TYPES:
                for prod in products:
                    if st.value in STYLE_SPLIT_TYPES:
                        for style in styles:
                            mk(cat_name, st_name, prod, style)
                    else:
                        mk(cat_name, st_name, prod)
            elif st.value == STEP_UNDER:
                for step in steps:
                    mk(cat_name, st_name, step)
            elif st.value == THEME_UNDER:
                for theme in themes:
                    mk(cat_name, st_name, theme)
            else:
                mk(cat_name, st_name)

    with open(os.path.join(out_root, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README.format(year=year, today=date.today().isoformat()))

    print(f"生成完成：{out_root}", flush=True)
    print(f"叶子文件夹 {made} 个（含中间层自动创建）", flush=True)


if __name__ == "__main__":
    main()
