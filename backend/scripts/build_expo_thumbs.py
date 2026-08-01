"""存量素材补生成列表缩略图（{stem}_thumb.jpg，长边 400 q82）——2026-08-01

背景：甄选页把发型封面渲成 76×92、发型库弹层也只有一格大小，而库里封面是
1024×1536 的 PNG、单张约 2MB。**即使浏览器缓存完美命中、一个网络请求都不发**，
平板每次进屏仍要从磁盘读 2MB 并解码 150 万像素，一屏 6 张就是 900 万像素——
表现出来就是「每次进入合成页面图片还是在重新加载」。

为什么既有的压缩没救它：`downscale_inplace` 的口径是「长边超过 1600 才压」，
而这些封面是 1024×1536，卡在阈值以下，一次都没被处理过，PNG 原样落盘。

范围（只做列表位会用到的素材，results 不做——效果图是整屏展示，已有 _disp 版）：
- wigs        发型封面与角度图
- hair_colors 色板图

幂等：缩略图已存在且比原图新的跳过，二次运行 changed=0。
不改原图、不改数据库路径——缩略图是约定式命名的同目录派生物，
序列化侧 `thumb_url or cover_url` 回退，跑不跑都不影响功能，只影响快慢。

执行：cd backend && python -m scripts.build_expo_thumbs [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.expo import ai_pipeline  # noqa: E402

SOURCE_DIRS = ("wigs", "hair_colors")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _needs_thumb(src: Path) -> bool:
    """已有且不比原图旧的缩略图跳过——支持「换了原图后重跑补新缩略图」。"""
    thumb = src.with_name(src.stem + ai_pipeline.THUMB_SUFFIX)
    if not thumb.exists():
        return True
    return thumb.stat().st_mtime < src.stat().st_mtime


def main() -> int:
    ap = argparse.ArgumentParser(description="存量 expo 素材补生成列表缩略图")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    args = ap.parse_args()

    scanned = skipped = changed = failed = 0
    saved_bytes = 0

    for name in SOURCE_DIRS:
        root = ai_pipeline.UPLOAD_ROOT / name
        if not root.exists():
            print(f"[skip] {root} 不存在")
            continue
        for src in sorted(root.iterdir()):
            # 派生物自身不参与（否则会出现 x_thumb_thumb.jpg）
            if not src.is_file() or src.suffix.lower() not in IMAGE_EXTS:
                continue
            if src.stem.endswith(ai_pipeline.THUMB_SUFFIX.split(".")[0]) or \
                    src.name.endswith(ai_pipeline.DISPLAY_SUFFIX):
                continue
            scanned += 1
            if not _needs_thumb(src):
                skipped += 1
                continue
            if args.dry_run:
                changed += 1
                continue
            thumb = ai_pipeline.make_thumb_image(src)
            if thumb is None:
                failed += 1
                continue
            changed += 1
            saved_bytes += src.stat().st_size - thumb.stat().st_size

    print(f"扫描 {scanned} / 跳过 {skipped} / 生成 {changed} / 失败 {failed}")
    if changed and not args.dry_run:
        print(f"列表位单张体积合计减少 {saved_bytes / 1024 / 1024:.1f} MB")
    if args.dry_run:
        print("(--dry-run，未写盘)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
