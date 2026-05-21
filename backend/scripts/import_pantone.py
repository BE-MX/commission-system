#!/usr/bin/env python3
"""导入 Pantone TCX 参考色库到 ark_pantone_reference 表

用法:
    cd backend
    python scripts/import_pantone.py

数据源: https://github.com/Margaret2/pantone-colors (JSON 格式，2310条)
"""

import json
import sys
import urllib.request

sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.color.models import PantoneReference
from app.color.calc_service import hex_to_rgb, rgb_to_lab

PANTONE_JSON_URL = (
    "https://raw.githubusercontent.com/Margaret2/pantone-colors/master/pantone-numbers.json"
)


def fetch_pantone_data():
    """从 GitHub 下载 Pantone JSON"""
    print(f"Downloading Pantone data from {PANTONE_JSON_URL} ...")
    with urllib.request.urlopen(PANTONE_JSON_URL, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(f"Downloaded {len(data)} Pantone colors")
    return data


def import_pantone():
    db = SessionLocal()
    try:
        # 检查是否已导入
        existing = db.query(PantoneReference).count()
        if existing > 0:
            print(f"Pantone table already has {existing} rows. Skipping import.")
            return

        data = fetch_pantone_data()

        for pantone_code, item in data.items():
            hex_code = item.get("hex", "")
            if not hex_code.startswith("#"):
                hex_code = f"#{hex_code}"

            rgb_norm = hex_to_rgb(hex_code)
            rgb_255 = (rgb_norm * 255).astype(int)
            lab = rgb_to_lab(rgb_norm)

            ref = PantoneReference(
                pantone_code=pantone_code + " TCX",
                pantone_name=item.get("name", ""),
                hex_code=hex_code.upper(),
                rgb_r=int(rgb_255[0]),
                rgb_g=int(rgb_255[1]),
                rgb_b=int(rgb_255[2]),
                lab_l=round(float(lab[0]), 2),
                lab_a=round(float(lab[1]), 2),
                lab_b_val=round(float(lab[2]), 2),
                collection="tcx",
            )
            db.add(ref)

        db.commit()
        print(f"Successfully imported {len(data)} Pantone colors")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_pantone()
