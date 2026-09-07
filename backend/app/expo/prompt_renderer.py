"""Render database-owned prose; only assembly and input selection live in code."""

import random

from app.expo.prompt_catalog import SCENES, TRYON_SCENES


def render_part(config: dict, key: str, **values) -> str:
    return config["parts"][key].format_map(values)


def wardrobe_clause(config: dict, uniform: bool = False) -> str:
    # Keep the historical random selection order: jewelry, then outfit.
    jewelry = (render_part(config, "jewelry", jewelry=random.choice(config["jewelry_options"]))
               if config["jewelry_options"] else "")
    if uniform or not config["outfit_options"]:
        return jewelry
    return render_part(config, "wardrobe", look=random.choice(config["outfit_options"])) + jewelry


def color_clause(config: dict, color: dict | None) -> str:
    if not color:
        return ""
    hex_value = color.get("hex") or ""
    description = (color.get("description") or "").strip()
    return render_part(
        config, "color_text", name=color.get("name_en") or color.get("name") or "",
        code=color.get("code") or "",
        hex_part=render_part(config, "color_hex", hex=hex_value) if hex_value else "",
        description=render_part(config, "color_description", description=description) if description else "",
    )


def render_prompt(session, row, wig, config: dict, resolve_path) -> tuple[str, list, str | None]:
    """Resolve images and all variable text once, before committing a generation."""
    images = [resolve_path(session.photo_path)]
    if row.wig_id is None and row.scene_json:
        scene = next((s for s in SCENES if s["key"] == row.scene_json.get("key")), None)
        if scene is None:
            raise ValueError("场景选择无效，请重新选择")
        prompt = (
            render_part(config, "scene_base", scene=config["scene_prompts"][f"scene:{scene['key']}"])
            + wardrobe_clause(config, uniform=bool(scene.get("uniform")))
            + render_part(config, "finish") + render_part(config, "scene_tail")
        )
        size = None
    else:
        if wig is None:
            raise ValueError("所选发型已不存在，请重新选择")
        color = row.hair_color_json or {}
        refs = [resolve_path(p) for p in (color.get("ref_photos") or [])[:3] if resolve_path(p).exists()]
        if refs:
            color_text = render_part(config, "color_reference")
        else:
            refs = [resolve_path(p) for p in (wig.angle_photos or [])[:3] if resolve_path(p).exists()]
            if not refs and wig.cover_path and resolve_path(wig.cover_path).exists():
                refs = [resolve_path(wig.cover_path)]
            color_text = color_clause(config, row.hair_color_json)
        images.extend(refs)
        key = (row.scene_json or {}).get("key")
        scene = next((s for s in TRYON_SCENES if s["key"] == key), None)
        if key and scene is None:
            raise ValueError("生成场景无效，请重新选择")
        if scene:
            scene_text = (
                render_part(config, "replace_background", scene=config["scene_prompts"][f"tryon:{key}"])
                + wardrobe_clause(config, uniform=bool(scene.get("uniform")))
                + render_part(config, "framing")
            )
        else:
            scene_text = render_part(config, "keep_background")
        prompt = (
            render_part(config, "tryon_base", description=wig.wig_description or wig.name,
                        extra=wig.composite_prompt or "")
            + color_text + scene_text + render_part(config, "finish")
            + render_part(config, "tryon_tail") + render_part(config, "portrait_spec")
        )
        size = "1024x1536"
    if not prompt.strip() or len(prompt) > 64000:
        raise ValueError("展开后的提示词为空或超过 64000 字，请调整版本配置")
    return prompt, images, size
