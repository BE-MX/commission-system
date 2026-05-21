"""色彩计算服务 — HEX/RGB/LAB/HSL转换、色差、混色、Pantone匹配、图片主色提取

依赖: colour-science, numpy, scikit-learn, opencv-python, Pillow
"""

from __future__ import annotations

import colorsys
import logging
from typing import List, Optional

import colour
import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session

from app.color.models import PantoneReference

logger = logging.getLogger("color.calc")

# ── 常量 ─────────────────────────────────────────────────
DELTA_E_ACCEPTABLE = 5.0   # 色差可接受阈值
DELTA_E_PERCEPTIBLE = 1.0  # 人眼可感知阈值
DELTA_E_MATCH = 3.0        # Pantone 匹配"视觉无差异"阈值
MAX_RETRIES = 3            # 色板图生成最大重试次数

# ── HEX/RGB/LAB/HSL 全格式转换 ───────────────────────────


def hex_to_rgb(hex_code: str) -> np.ndarray:
    """HEX → 归一化 RGB (0-1, float64)"""
    hex_code = hex_code.lstrip("#")
    if len(hex_code) != 6:
        raise ValueError(f"Invalid HEX code: {hex_code}")
    rgb = np.array([int(hex_code[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)
    return rgb / 255.0


def rgb_to_hex(rgb: np.ndarray) -> str:
    """归一化 RGB (0-1) → HEX"""
    rgb_255 = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    return f"#{rgb_255[0]:02X}{rgb_255[1]:02X}{rgb_255[2]:02X}"


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """归一化 RGB (0-1) → CIE LAB"""
    xyz = colour.sRGB_to_XYZ(rgb, apply_cctf_decoding=True)
    lab = colour.XYZ_to_Lab(xyz, illuminant=colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"]["D65"])
    return lab


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """CIE LAB → 归一化 RGB (0-1)"""
    xyz = colour.Lab_to_XYZ(lab, illuminant=colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"]["D65"])
    rgb = colour.XYZ_to_sRGB(xyz, apply_cctf_encoding=True)
    return np.clip(rgb, 0.0, 1.0)


def rgb_to_hsl(rgb: np.ndarray) -> tuple:
    """归一化 RGB (0-1) → HSL (色相0-360, 饱和度0-100, 亮度0-100)"""
    h, l, s = colorsys.rgb_to_hls(rgb[0], rgb[1], rgb[2])
    return (h * 360, s * 100, l * 100)


def hex_to_all_formats(hex_code: str) -> dict:
    """HEX → 全格式（RGB/LAB/HSL）"""
    rgb_norm = hex_to_rgb(hex_code)
    rgb_255 = (rgb_norm * 255).astype(int).tolist()
    lab = rgb_to_lab(rgb_norm)
    hsl = rgb_to_hsl(rgb_norm)
    return {
        "hex": hex_code.upper(),
        "rgb": rgb_255,
        "lab": [round(float(v), 2) for v in lab],
        "hsl": [round(float(hsl[0]), 1), round(float(hsl[1]), 2), round(float(hsl[2]), 2)],
    }


# ── ΔE2000 色差计算 ──────────────────────────────────────


def calculate_delta_e(hex_a: str, hex_b: str) -> float:
    """计算两色 ΔE2000 色差"""
    lab_a = rgb_to_lab(hex_to_rgb(hex_a))
    lab_b = rgb_to_lab(hex_to_rgb(hex_b))
    return float(colour.delta_E(lab_a, lab_b, method="CIE 2000"))


def delta_e_assessment(delta_e: float) -> dict:
    """ΔE 值评估"""
    return {
        "delta_e_2000": round(delta_e, 2),
        "perceptible": delta_e >= DELTA_E_PERCEPTIBLE,
        "acceptable": delta_e < DELTA_E_ACCEPTABLE,
    }


# ── LAB 空间加权混色 ─────────────────────────────────────


def blend_colors_lab(components: list[dict]) -> dict:
    """
    在 LAB 空间做加权线性插值。
    components: [{"hex": "#6B5A52", "weight": 0.5}, ...]
    返回: {"hex": "#...", "lab": [...]}
    """
    if not components:
        raise ValueError("components cannot be empty")

    total_weight = sum(c["weight"] for c in components)
    if abs(total_weight - 1.0) > 0.01:
        # 归一化权重
        components = [{**c, "weight": c["weight"] / total_weight} for c in components]

    labs = [rgb_to_lab(hex_to_rgb(c["hex"])) for c in components]
    weights = [c["weight"] for c in components]

    blended_lab = np.average(labs, axis=0, weights=weights)
    blended_rgb = lab_to_rgb(blended_lab)
    blended_hex = rgb_to_hex(blended_rgb)

    return {
        "hex": blended_hex,
        "lab": [round(float(v), 2) for v in blended_lab],
    }


# ── Pantone 最近匹配 ─────────────────────────────────────


def find_nearest_pantone(target_hex: str, db: Session) -> Optional[dict]:
    """遍历 Pantone 库，找 ΔE2000 最小值"""
    target_lab = rgb_to_lab(hex_to_rgb(target_hex))

    refs = db.query(PantoneReference).all()
    if not refs:
        return None

    best_match = None
    min_de = float("inf")

    for p in refs:
        if p.lab_l is None or p.lab_a is None or p.lab_b_val is None:
            continue
        p_lab = np.array([float(p.lab_l), float(p.lab_a), float(p.lab_b_val)])
        de = float(colour.delta_E(target_lab, p_lab, method="CIE 2000"))
        if de < min_de:
            min_de = de
            best_match = p

    if best_match is None:
        return None

    return {
        "pantone_code": best_match.pantone_code,
        "pantone_name": best_match.pantone_name,
        "delta_e": round(min_de, 2),
    }


# ── 莱莎色库最近匹配 ─────────────────────────────────────


def find_nearest_palette(target_hex: str, db: Session) -> Optional[dict]:
    """匹配莱莎 color_palette 表中最近的色号"""
    from app.color.models import ColorPalette

    target_lab = rgb_to_lab(hex_to_rgb(target_hex))

    palettes = db.query(ColorPalette).all()
    if not palettes:
        return None

    best = None
    min_de = float("inf")

    for p in palettes:
        if p.lab_l is None or p.lab_a is None or p.lab_b_val is None:
            continue
        p_lab = np.array([float(p.lab_l), float(p.lab_a), float(p.lab_b_val)])
        de = float(colour.delta_E(target_lab, p_lab, method="CIE 2000"))
        if de < min_de:
            min_de = de
            best = p

    if best is None:
        return None

    return {
        "id": best.id,
        "code": best.industry_code,
        "name": best.display_name,
        "hex": best.hex_code,
        "delta_e": round(min_de, 2),
    }


# ── 图片主色提取 (OpenCV + K-means) ──────────────────────


def extract_dominant_colors(image_path: str, k: int = 5) -> List[dict]:
    """
    OpenCV + K-means 提取图片 Top-K 主色。
    返回: [{"hex": "#...", "rgb": [r,g,b], "percentage": 34.2}, ...]
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    # 缩小图片加速 K-means
    h, w = img.shape[:2]
    if max(h, w) > 800:
        scale = 800 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    pixels = img.reshape(-1, 3).astype(np.float32)

    # 排除纯白/纯黑/接近边缘的像素（减少背景干扰）
    # 这里简单处理：如果图片边缘有大量相似色，K-means 会自动聚类
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
    kmeans.fit(pixels)

    centers = kmeans.cluster_centers_.astype(int)
    counts = np.bincount(kmeans.labels_, minlength=k)
    percentages = counts / counts.sum() * 100

    results = []
    for center, pct in sorted(zip(centers, percentages), key=lambda x: -x[1]):
        hex_code = f"#{center[0]:02X}{center[1]:02X}{center[2]:02X}"
        results.append({
            "hex": hex_code,
            "rgb": center.tolist(),
            "percentage": round(float(pct), 1),
        })
    return results


# ── 色板图色差校验 ───────────────────────────────────────


def verify_swatch_color(image_path: str, target_hex: str) -> dict:
    """
    生成色板图后，提取主色与目标色做 ΔE 校验。
    返回: {"target_hex": ..., "actual_hex": ..., "delta_e": ..., "pass_check": bool}
    """
    colors = extract_dominant_colors(image_path, k=3)
    actual_hex = colors[0]["hex"]  # 取占比最大的颜色
    de = calculate_delta_e(target_hex, actual_hex)
    return {
        "target_hex": target_hex.upper(),
        "actual_hex": actual_hex,
        "delta_e": round(de, 2),
        "pass_check": de < DELTA_E_ACCEPTABLE,
    }


# ── 辅助：从 HEX 计算完整色彩数据（用于色号入库） ─────────


def compute_color_data(hex_code: str) -> dict:
    """
    输入 HEX，计算 RGB/LAB/HSL 全格式 + Pantone 匹配。
    返回可直接用于创建 ColorPalette 的字典。
    """
    all_fmt = hex_to_all_formats(hex_code)
    return {
        "hex_code": all_fmt["hex"],
        "rgb_r": all_fmt["rgb"][0],
        "rgb_g": all_fmt["rgb"][1],
        "rgb_b": all_fmt["rgb"][2],
        "lab_l": all_fmt["lab"][0],
        "lab_a": all_fmt["lab"][1],
        "lab_b_val": all_fmt["lab"][2],
        "hsl_h": int(all_fmt["hsl"][0]) if all_fmt["hsl"][0] is not None else None,
        "hsl_s": all_fmt["hsl"][1],
        "hsl_l": all_fmt["hsl"][2],
    }


# ── Prompt 模板 ──────────────────────────────────────────

SWATCH_PROMPTS = {
    "swatch_card": """Professional hair color swatch card showing real human hair
extension strands in color {color_name} ({hex_code}).
Shot on pure white background with D65 standard illuminant studio lighting.
Multiple individual hair strands fanned out to show color depth and dimension.
The hair appears natural with subtle light reflection. Color-accurate representation.
No text, no labels, no human model.""",

    "hair_strand": """Close-up macro photograph of a bundle of real human hair
extensions in {color_name} color ({hex_code}).
The hair bundle is held together showing the texture and color variation.
Studio lighting on neutral grey background. Focus on color accuracy and hair texture.
Photorealistic, 8K quality.""",

    "model_preview": """Professional photo of the back of a woman's head showing
hair extensions installed, color: {color_name} ({hex_code}).
Hair is styled in loose waves to show the color dimension.
Clean studio background, natural lighting. No face visible.
Focus on color accuracy of the hair.""",
}


def build_swatch_prompt(hex_code: str, color_name: str, style: str) -> str:
    """构建色板图生成 Prompt"""
    template = SWATCH_PROMPTS.get(style, SWATCH_PROMPTS["swatch_card"])
    return template.format(color_name=color_name, hex_code=hex_code)
