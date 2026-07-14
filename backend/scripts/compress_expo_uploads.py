"""存量图片压缩：expo 素材原地降采样 + 结果图补生成 kiosk 展示版（2026-07-14）

背景：生产 /uploads 全部经 frp 隧道回源，展会现场大图（发型库手机原片 3~8MB、
结果 PNG 3~5MB）挤占隧道带宽，把 kiosk 轮询挤成 Network Error。上传端点已改为
落盘即压（ai_pipeline.downscale_inplace）、合成落盘即生成展示版（make_display_image），
本脚本对**存量**文件补一轮同口径处理。

范围与口径：
- wigs / hair_colors：原地降采样（长边 1600，保持文件名与扩展名 → 数据库路径零变更）
- scenes：原地降采样（长边 1200，与 save_scene_image 口径一致）
- photos：原地降采样（长边 1600；客户照片是"佩戴前"对比图，也走隧道）
- results：不动原图（留档），只为缺展示版的成品补 {stem}_disp.jpg

幂等：尺寸已达标的跳过、展示版已存在的跳过，二次运行 changed=0。
开发机跑完后，wigs/hair_colors/scenes 需按既有流程打包拷贝到生产同目录；
或直接在生产机器上跑本脚本（不依赖数据库）。

执行：cd backend && python -m scripts.compress_expo_uploads [--dry-run]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.expo import ai_pipeline  # noqa: E402

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 目录 → 降采样长边（与各上传端点的落盘口径一一对应）
_INPLACE_PLAN = [
    (ai_pipeline.UPLOAD_ROOT / "wigs", ai_pipeline.UPLOAD_MAX_EDGE),
    (ai_pipeline.UPLOAD_ROOT / "hair_colors", ai_pipeline.UPLOAD_MAX_EDGE),
    (ai_pipeline.SCENE_IMAGE_DIR, 1200),
    (ai_pipeline.PHOTO_DIR, ai_pipeline.UPLOAD_MAX_EDGE),
]


def _fmt(n: int) -> str:
    return f"{n / 1024 / 1024:.2f}MB" if n >= 1024 * 1024 else f"{n / 1024:.0f}KB"


def compress_inplace(dry_run: bool) -> tuple[int, int, int]:
    changed = before_total = after_total = 0
    for folder, max_edge in _INPLACE_PLAN:
        if not folder.is_dir():
            print(f"skip（目录不存在）: {folder}")
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _IMG_EXTS:
                continue
            before = path.stat().st_size
            if dry_run:
                # 与真实执行同口径：尺寸已达标的不算（downscale_inplace 会跳过）
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        if max(im.size) <= max_edge:
                            continue
                except Exception:
                    continue  # 解码失败真实执行也不会动它
                print(f"[dry-run] would compress {path.relative_to(ai_pipeline.REPO_ROOT)} ({_fmt(before)})")
                continue
            ai_pipeline.downscale_inplace(path, max_edge)
            after = path.stat().st_size
            if after != before:
                changed += 1
                before_total += before
                after_total += after
                print(f"compressed {path.relative_to(ai_pipeline.REPO_ROOT)}: {_fmt(before)} -> {_fmt(after)}")
    return changed, before_total, after_total


def gen_display(dry_run: bool) -> int:
    """为存量成品补展示版：老会话在销售面板图集里仍会被翻看。"""
    made = 0
    folder = ai_pipeline.RESULT_DIR
    if not folder.is_dir():
        print(f"skip（目录不存在）: {folder}")
        return 0
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _IMG_EXTS:
            continue
        if path.stem.endswith("_disp"):  # 自身就是展示版
            continue
        disp = path.with_name(path.stem + ai_pipeline.DISPLAY_SUFFIX)
        if disp.exists():
            continue
        if dry_run:
            print(f"[dry-run] would create {disp.relative_to(ai_pipeline.REPO_ROOT)}")
            continue
        if ai_pipeline.make_display_image(path):
            made += 1
            print(f"display {disp.relative_to(ai_pipeline.REPO_ROOT)} ({_fmt(disp.stat().st_size)})")
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="只列出将处理的文件，不写盘")
    args = parser.parse_args()

    changed, before, after = compress_inplace(args.dry_run)
    made = gen_display(args.dry_run)
    if not args.dry_run:
        saved = before - after
        print(f"\n完成：原地压缩 {changed} 个文件（{_fmt(before)} -> {_fmt(after)}，省 {_fmt(max(saved, 0))}），"
              f"补展示版 {made} 张")


if __name__ == "__main__":
    main()
