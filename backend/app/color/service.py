"""发色数字化 — Service Facade

向后兼容：from app.color.service import X 仍然可用。
新代码建议直接 import 子模块。
"""

# 色号 CRUD
from app.color.palette_service import (
    create_palette,
    delete_palette,
    get_palette,
    get_palette_filter_options,
    list_palettes,
    update_palette,
)

# 混合色 CRUD
from app.color.blend_service import (
    create_blend,
    delete_blend,
    get_blend,
    get_blend_detail,
    get_blend_filter_options,
    list_blends,
    update_blend,
)

# 色板图生成
from app.color.swatch_service import (
    batch_generate_swatch,
    create_swatch_task,
    generate_swatch_image,
    get_swatch,
    list_swatches,
    verify_swatch_task,
)

# 色彩计算
from app.color.calc_service import (
    blend_colors_lab,
    build_swatch_prompt,
    calculate_delta_e,
    compute_color_data,
    delta_e_assessment,
    extract_dominant_colors,
    find_nearest_palette,
    find_nearest_pantone,
    hex_to_all_formats,
    verify_swatch_color,
)

__all__ = [
    # palette
    "create_palette",
    "delete_palette",
    "get_palette",
    "get_palette_filter_options",
    "list_palettes",
    "update_palette",
    # blend
    "create_blend",
    "delete_blend",
    "get_blend",
    "get_blend_detail",
    "get_blend_filter_options",
    "list_blends",
    "update_blend",
    # swatch
    "batch_generate_swatch",
    "create_swatch_task",
    "generate_swatch_image",
    "get_swatch",
    "list_swatches",
    "verify_swatch_task",
    # calc
    "blend_colors_lab",
    "build_swatch_prompt",
    "calculate_delta_e",
    "compute_color_data",
    "delta_e_assessment",
    "extract_dominant_colors",
    "find_nearest_palette",
    "find_nearest_pantone",
    "hex_to_all_formats",
    "verify_swatch_color",
]
