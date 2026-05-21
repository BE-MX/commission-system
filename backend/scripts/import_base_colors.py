#!/usr/bin/env python3
"""导入基础色号到 ark_color_palette 表

用法:
    cd backend
    python scripts/import_base_colors.py

数据来源: 需求文档附录 C（行业通用色号）
"""

import sys

sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.color.models import ColorPalette
from app.color.calc_service import compute_color_data

# 基础色号数据（来自需求文档附录 C）
BASE_COLORS = [
    ("#1", "乌黑", "Jet Black", "#0E0E10", "cool", "low", "black", "19-4004 TCX", "industry", True),
    ("#1B", "自然黑", "Off Black / Natural Black", "#1A1718", "warm", "low", "black", "19-3906 TCX", "industry", True),
    ("#2", "深棕", "Darkest Brown", "#2C1B18", "warm", "low", "brown", "19-1414 TCX", "industry", True),
    ("#4", "巧克力棕", "Chocolate Brown", "#411900", "warm", "medium-low", "brown", "19-1322 TCX", "industry", True),
    ("#6", "栗棕", "Chestnut Brown", "#5C3A21", "warm", "medium", "brown", "18-1140 TCX", "industry", True),
    ("#8", "灰棕", "Ash Brown", "#6B5A52", "cool", "medium", "brown", "17-1118 TCX", "industry", True),
    ("#18", "脏金", "Dirty Blonde", "#BCA384", "neutral", "medium-high", "blonde", "15-1214 TCX", "industry", True),
    ("#27", "蜜金", "Honey Blonde / Strawberry", "#D19B53", "warm", "high", "blonde", "15-1040 TCX", "industry", True),
    ("#60", "白金", "Platinum / Ash Blonde", "#F3ECDE", "cool", "very-high", "blonde", "11-0604 TCX", "industry", True),
    ("#613", "极浅金", "Light Blonde / Bleach", "#F5DEB3", "warm", "very-high", "blonde", "12-0815 TCX", "industry", True),
    ("#33", "亮红", "Dark Auburn / Vibrant Red", "#6A281E", "warm", "medium", "red", "19-1543 TCX", "industry", True),
    ("#99J", "勃艮第", "Burgundy / Plum", "#501A24", "cool", "medium-low", "red", "19-1725 TCX", "industry", True),
]


def import_base_colors():
    db = SessionLocal()
    try:
        existing = db.query(ColorPalette).count()
        if existing > 0:
            print(f"Color palette already has {existing} rows. Skipping import.")
            return

        for code, name, name_en, hex_code, undertone, luminance, family, pantone, source, is_stock in BASE_COLORS:
            computed = compute_color_data(hex_code)

            palette = ColorPalette(
                industry_code=code,
                display_name=name,
                display_name_en=name_en,
                hex_code=hex_code.upper(),
                rgb_r=computed["rgb_r"],
                rgb_g=computed["rgb_g"],
                rgb_b=computed["rgb_b"],
                lab_l=computed["lab_l"],
                lab_a=computed["lab_a"],
                lab_b_val=computed["lab_b_val"],
                hsl_h=computed["hsl_h"],
                hsl_s=computed["hsl_s"],
                hsl_l=computed["hsl_l"],
                undertone=undertone,
                luminance_level=luminance,
                color_family=family,
                pantone_tcx=pantone,
                source=source,
                is_leshine_stock=1 if is_stock else 0,
            )
            db.add(palette)

        db.commit()
        print(f"Successfully imported {len(BASE_COLORS)} base colors")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_base_colors()
