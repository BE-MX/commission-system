"""expo 图片压缩链路测试（2026-07-14 网络拥堵治理）。

覆盖三块：
- downscale_inplace：上传落盘即压（超边长才动、保持扩展名、失败不阻断）
- make_display_image / display_rel_for：结果图 kiosk 展示版的生成与探测
- serialize_session：display_url 契约（有展示版给压缩 URL，历史结果回退 None）
"""

from pathlib import Path

from PIL import Image

from app.expo import ai_pipeline, service
from app.expo.models import ExpoResult, ExpoSession
from app.expo.schemas import CustomerRegister


def _write_img(path, size=(2400, 1600), color="red", **save_kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, **save_kwargs)
    return path


class TestDownscaleInplace:
    def test_large_jpeg_downscaled_keeps_name(self, tmp_path):
        p = _write_img(tmp_path / "wig_big.jpg", size=(3200, 2400), quality=95)
        before = p.stat().st_size
        ai_pipeline.downscale_inplace(p, 1600)
        with Image.open(p) as im:
            assert max(im.size) == 1600
        assert p.exists() and p.suffix == ".jpg"
        assert p.stat().st_size < before

    def test_small_file_untouched_byte_identical(self, tmp_path):
        p = _write_img(tmp_path / "wig_small.jpg", size=(800, 600))
        before = p.read_bytes()
        ai_pipeline.downscale_inplace(p, 1600)
        assert p.read_bytes() == before  # 已达标不重编码，避免无谓有损

    def test_png_keeps_extension(self, tmp_path):
        p = _write_img(tmp_path / "scene.png", size=(3000, 1500))
        ai_pipeline.downscale_inplace(p, 1200)
        with Image.open(p) as im:
            assert max(im.size) == 1200
            assert im.format == "PNG"  # 扩展名与真实格式一致，存库路径零变更

    def test_unreadable_file_kept_as_is(self, tmp_path):
        p = tmp_path / "broken.jpg"
        p.write_bytes(b"not an image")
        ai_pipeline.downscale_inplace(p, 1600)
        assert p.read_bytes() == b"not an image"  # 失败静默保留，不阻断上传


class TestDisplayImage:
    def test_make_display_creates_disp_jpg_and_keeps_original(self, tmp_path):
        src = _write_img(tmp_path / "expo_1_abcd.png", size=(1440, 2160))
        original = src.read_bytes()
        disp = ai_pipeline.make_display_image(src)
        assert disp is not None and disp.name == "expo_1_abcd_disp.jpg"
        with Image.open(disp) as im:
            assert max(im.size) == ai_pipeline.DISPLAY_MAX_EDGE
            assert im.format == "JPEG"
        assert src.read_bytes() == original  # 原图留档口径不动

    def test_make_display_unreadable_returns_none(self, tmp_path):
        src = tmp_path / "expo_2_bad.png"
        src.write_bytes(b"garbage")
        assert ai_pipeline.make_display_image(src) is None

    def test_display_rel_for_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
        src = _write_img(tmp_path / "uploads" / "expo" / "results" / "expo_3_cd.png",
                         size=(1200, 1800))
        rel = "uploads/expo/results/expo_3_cd.png"
        assert ai_pipeline.display_rel_for(rel) is None  # 展示版未生成 → None
        ai_pipeline.make_display_image(src)
        assert ai_pipeline.display_rel_for(rel) == "uploads/expo/results/expo_3_cd_disp.jpg"
        assert ai_pipeline.display_rel_for(None) is None


class TestStampLogo:
    """品牌水印叠加（2026-07-31）。水印是对外输出的品牌资产，但绝不能阻断合成。"""

    @staticmethod
    def _corner(path, frac=0.12):
        """右下角区域的像素集合——水印落点。"""
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            return list(im.crop((int(w * (1 - frac)), int(h * (1 - frac)), w, h)).getdata())

    @staticmethod
    def _topleft(path, frac=0.12):
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            return list(im.crop((0, 0, int(w * frac), int(h * frac))).getdata())

    def test_stamps_bottom_right_only(self, tmp_path):
        p = _write_img(tmp_path / "expo_1_a.png", size=(1024, 1536), color="red")
        before_corner, before_top = self._corner(p), self._topleft(p)
        assert ai_pipeline.stamp_logo(p) is True
        assert self._corner(p) != before_corner   # 右下角被水印改写
        assert self._topleft(p) == before_top     # 画面主体不受影响

    @staticmethod
    def _stamped_bbox(path, size):
        """盖章前后的差异框。底图用中灰而非纯白——白底上浅色水印像素差极小，
        缩放改坏了测试照样绿（审查 2026-07-31）。"""
        from PIL import ImageChops

        _write_img(path, size=size, color=(128, 128, 128))
        base = Image.open(path).convert("RGB").copy()
        ai_pipeline.stamp_logo(path)
        with Image.open(path) as im:
            return ImageChops.difference(im.convert("RGB"), base).getbbox()

    def test_scales_with_image_width(self, tmp_path):
        """不同产物规格下角标占比一致——中转站不严格遵守 size，写死像素会忽大忽小。"""
        small = self._stamped_bbox(tmp_path / "s.png", (800, 1200))
        large = self._stamped_bbox(tmp_path / "l.png", (1600, 2400))
        assert abs((small[2] - small[0]) / 800 - (large[2] - large[0]) / 1600) < 0.02

    @staticmethod
    def _stamp_stats(path, level):
        """在指定灰度平底上盖章，回角标框内的统计量。

        返回 (中位亮度, >150 占比, 最亮值, 有色像素占比)。有色 = max-min 通道差 >25，
        用来区分品牌彩版与纯白单色版——只看亮度是分不出这两者的。
        """
        import statistics

        from PIL import ImageChops

        p = _write_img(path, size=(1024, 1536), color=(level, level, level))
        base = Image.open(p).convert("RGB").copy()
        assert ai_pipeline.stamp_logo(p) is True
        with Image.open(p) as im:
            im = im.convert("RGB")
            px = list(im.crop(ImageChops.difference(im, base).getbbox()).getdata())
        lum = [sum(v) / 3 for v in px]
        return (statistics.median(lum),
                sum(1 for v in lum if v > 150) / len(px),
                max(lum),
                sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 25) / len(px))

    def test_watermark_leaves_no_backing_plate(self, tmp_path):
        """水印是裸线稿：灰底板、白外发光都已废弃（2026-07-31 亮哥两次指令）。

        判据是角标框内的**中位亮度仍等于背景**——线稿稀疏，压不动中位数；
        任何一种「底」铺进来都会立刻把它顶走。只看「有没有像素被改写」测不出底。
        中位数这条对彩版白版都成立，故两条路径都验（实测 128 底 →128、40 底 →41）。
        """
        light = self._stamp_stats(tmp_path / "bare_light.png", 128)
        dark = self._stamp_stats(tmp_path / "bare_dark.png", 40)
        assert abs(light[0] - 128) <= 3, f"浅底上角标中位亮度 {light[0]:.0f}，疑似有底板"
        assert abs(dark[0] - 40) <= 3, f"深底上角标中位亮度 {dark[0]:.0f}，疑似有底板"
        assert light[1] < 0.15, f"浅底上 {light[1]:.0%} 的像素明显偏亮，疑似底板/外发光回归"

    def test_dark_backdrop_switches_to_white_variant(self, tmp_path):
        """深色落点换纯白单色版——这是「不加底又要可读」的唯一解法。

        两条断言缺一不可：够亮（最亮 >200，可读性回来了）+ 没有品牌色残留
        （有色像素 <2%，确认真的换了版而不是彩版凑巧撞上亮像素）。
        """
        median, _, brightest, saturated = self._stamp_stats(tmp_path / "dk.png", 40)
        assert brightest > 200, f"深底上水印最亮仅 {brightest:.0f}，中文会糊进背景"
        assert saturated < 0.02, f"深底上仍有 {saturated:.0%} 有色像素，没切到单色版"

    def test_light_backdrop_keeps_brand_colour(self, tmp_path):
        """浅色落点保留品牌彩版——阈值取 100 而非可读性交叉点 150，就是为了这个：
        实拍照片落点多在 120~140，按交叉点切会让品牌色几乎不再出现（实测样张 138/121）。
        """
        *_, saturated = self._stamp_stats(tmp_path / "lt.png", 128)
        assert saturated > 0.15, f"浅底上有色像素仅 {saturated:.0%}，品牌彩版丢了"

    def test_variant_switch_tracks_the_threshold(self, tmp_path):
        """阈值两侧各取一档，锁住切换方向本身——单看某一档过不了防反接。"""
        below = self._stamp_stats(tmp_path / "below.png", 80)[3]
        above = self._stamp_stats(tmp_path / "above.png", 140)[3]
        assert below < 0.02, f"落点亮度 80 应判深色走白版，实得有色像素 {below:.0%}"
        assert above > 0.15, f"落点亮度 140 应判浅色走彩版，实得有色像素 {above:.0%}"

    def test_logo_asset_has_no_opaque_backing(self):
        """素材侧的同一条约束：孔雀徽章内部不得是不透明纯白。

        只去代码里的光晕、留着素材白底等于没去。品牌物料重新导出极易带回白底，
        而那是「图正常、只是水印像贴纸」的静默回归，展位现场没人会报障。
        """
        with Image.open(ai_pipeline.LOGO_PATH) as raw:
            logo = raw.convert("RGBA")
        px = logo.load()
        w, h = logo.size
        solid_white = sum(1 for y in range(0, h, 3) for x in range(0, w, 3)
                          if px[x, y][3] > 250 and min(px[x, y][:3]) >= 250)
        assert solid_white == 0, f"素材仍有 {solid_white} 个不透明纯白像素（抽样），白底没去干净"

    def test_idempotent_second_stamp_is_noop(self, tmp_path):
        """存量补水印脚本重跑一遍不能把半透明底板叠成不透明色块。"""
        p = _write_img(tmp_path / "expo_idem.png", size=(1024, 1536), color=(60, 60, 60))
        assert ai_pipeline.stamp_logo(p) is True
        once = p.read_bytes()
        assert ai_pipeline.stamp_logo(p) is True   # 幂等返回，不再改写
        assert p.read_bytes() == once

    def test_jpeg_content_not_reencoded_as_png(self, tmp_path):
        """_save_result_image 一律写 .png，但其 URL 分支接受 jpg——换供应商后
        真实 JPEG 若按扩展名当 PNG 重编码会膨胀数倍打进隧道（审查 2026-07-31）。"""
        p = tmp_path / "expo_jpeg_in_png.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 1536), (90, 120, 150)).save(p, "JPEG", quality=88)
        before = p.stat().st_size
        assert ai_pipeline.stamp_logo(p) is True
        with Image.open(p) as im:
            assert im.format == "JPEG"          # 按真实格式写回，不改扩展名
        assert p.stat().st_size < before * 3    # 没有被重编码成 PNG 而膨胀

    def test_landscape_watermark_not_oversized(self):
        """scene 模式产出横版/方形：LOGO 是竖长条，按宽度定比例会撑到画面高的三成。
        基准取短边后，角标高度占比在各种画幅下都必须收敛。"""
        import tempfile
        from PIL import ImageChops

        def height_ratio(size):
            with tempfile.TemporaryDirectory() as d:
                p = _write_img(Path(d) / "r.png", size=size, color="white")
                base = Image.open(p).convert("RGB").copy()
                ai_pipeline.stamp_logo(p)
                with Image.open(p) as im:
                    box = ImageChops.difference(im.convert("RGB"), base).getbbox()
            return (box[3] - box[1]) / size[1]

        portrait = height_ratio((1024, 1536))
        landscape = height_ratio((1536, 1024))
        square = height_ratio((1024, 1024))
        assert landscape < 0.26, f"横版角标过高: {landscape:.0%}"
        assert square < 0.26, f"方形角标过高: {square:.0%}"
        assert portrait < 0.26

    def test_missing_logo_does_not_break_image(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_pipeline, "LOGO_PATH", tmp_path / "nope.png")
        p = _write_img(tmp_path / "expo_2_b.png", size=(600, 900))
        original = p.read_bytes()
        assert ai_pipeline.stamp_logo(p) is False   # 不抛异常
        assert p.read_bytes() == original           # 原图完好，合成继续

    def test_unreadable_image_returns_false(self, tmp_path):
        p = tmp_path / "expo_3_bad.png"
        p.write_bytes(b"garbage")
        assert ai_pipeline.stamp_logo(p) is False
        assert p.read_bytes() == b"garbage"

    def test_opaque_png_stays_rgb(self, tmp_path):
        """不透明原图不该凭空多出 alpha 通道（RGBA PNG 体积 +33%，要经隧道回源）。"""
        p = _write_img(tmp_path / "expo_4_c.png", size=(1024, 1536), color="navy")
        ai_pipeline.stamp_logo(p)
        with Image.open(p) as im:
            assert im.mode == "RGB"

    def test_jpeg_source_keeps_format(self, tmp_path):
        p = _write_img(tmp_path / "expo_5_d.jpg", size=(1024, 1536), color="teal", quality=95)
        assert ai_pipeline.stamp_logo(p) is True
        with Image.open(p) as im:
            assert im.format == "JPEG"

    def test_startup_check_warns_but_never_blocks(self, monkeypatch, capsys):
        """LOGO 缺失时启动自检要出声（否则现场只会看到「图正常、没水印」），
        但绝不能抛异常——展位后端起不来远比少个角标严重。"""
        from app.bootstrap.resources import check_expo_watermark

        assert check_expo_watermark() is True     # 资产随代码库分发，正常在位
        monkeypatch.setattr(ai_pipeline, "LOGO_PATH", Path("/nonexistent/logo.png"))
        assert check_expo_watermark() is False    # 不抛异常
        assert "水印" in capsys.readouterr().out  # NSSM service.log 只认 print

    def test_stamp_precedes_display_in_composite_flow(self):
        """展示版由原图派生：stamp 若晚于 make_display_image，kiosk 屏会静默拿到
        无水印展示版，现场无人察觉。直接锚源码顺序——打桩整条 _run_composite 要 mock
        掉 DB/AI/文件系统三层，维护成本高于它能挡的风险。"""
        import inspect

        src = inspect.getsource(ai_pipeline._run_composite)
        assert src.index("stamp_logo(") < src.index("make_display_image(")

    def test_display_version_inherits_watermark(self, tmp_path):
        """展示版由原图派生：先盖章后派生，kiosk 屏上也必须有 LOGO。"""
        p = _write_img(tmp_path / "expo_6_e.png", size=(1024, 1536), color="red")
        ai_pipeline.stamp_logo(p)
        disp = ai_pipeline.make_display_image(p)
        assert disp is not None
        with Image.open(disp) as im:
            w, h = im.size
            corner = list(im.convert("RGB").crop(
                (int(w * 0.8), int(h * 0.85), w, h)).getdata())
        assert any(px != (255, 0, 0) for px in corner)  # 纯红底上出现了水印像素


class TestThumbImage:
    """列表缩略图（2026-08-01）：甄选页把 1024×1536/2MB 的封面渲成 76px，
    即使缓存完美命中，每次进屏仍要解码 150 万像素——表现就是「像在重新加载」。"""

    def test_thumb_is_smaller_in_both_pixels_and_bytes(self, tmp_path):
        p = _write_img(tmp_path / "wig_x.png", size=(1024, 1536), color=(120, 90, 70))
        thumb = ai_pipeline.make_thumb_image(p)
        assert thumb is not None and thumb.name == "wig_x_thumb.jpg"
        with Image.open(thumb) as im:
            assert max(im.size) == ai_pipeline.THUMB_MAX_EDGE
        assert thumb.stat().st_size < p.stat().st_size

    def test_small_source_is_not_upscaled(self, tmp_path):
        """已经比阈值小的图只转码不放大——放大既没收益又糊。"""
        p = _write_img(tmp_path / "wig_s.png", size=(120, 160), color="teal")
        with Image.open(ai_pipeline.make_thumb_image(p)) as im:
            assert im.size == (120, 160)

    def test_thumb_url_falls_back_when_missing(self, tmp_path, monkeypatch):
        """存量素材在批处理跑完之前没有缩略图——必须回退原图，不能让列表变空白。"""
        monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
        rel = "uploads/expo/wigs/wig_none.png"
        (tmp_path / "uploads/expo/wigs").mkdir(parents=True)
        (tmp_path / rel).write_bytes(b"x")
        assert ai_pipeline.thumb_url_for(rel) is None
        assert ai_pipeline.thumb_url_for(None) is None

    def test_thumb_url_points_at_the_derived_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
        d = tmp_path / "uploads/expo/wigs"
        d.mkdir(parents=True)
        src = _write_img(d / "wig_y.png", size=(800, 800), color="navy")
        ai_pipeline.make_thumb_image(src)
        assert ai_pipeline.thumb_url_for("uploads/expo/wigs/wig_y.png") ==             "/uploads/expo/wigs/wig_y_thumb.jpg"

    def test_unreadable_source_returns_none_not_raise(self, tmp_path):
        """上传路径上调用——生成失败绝不能把上传顶成 500。"""
        bad = tmp_path / "broken.png"
        bad.write_bytes(b"not-an-image")
        assert ai_pipeline.make_thumb_image(bad) is None


class TestSerializeDisplayUrl:
    def _session_with_result(self, db, image_rel):
        customer = service.register_customer(db, CustomerRegister(
            name="测试客", phone="13800000000", wechat_id="",
            primary_need="volume", style_pref="知性优雅",
            consent=True, expo_code="2026-08-expo",
        ))
        session = ExpoSession(customer_id=customer.id, photo_path="uploads/expo/photos/p.jpg",
                              status="done")
        db.add(session)
        db.flush()
        db.add(ExpoResult(session_id=session.id, status="done", image_path=image_rel))
        db.commit()
        return session

    def test_display_url_present_when_disp_exists(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
        src = _write_img(tmp_path / "uploads" / "expo" / "results" / "expo_9_ef.png",
                         size=(1200, 1800))
        ai_pipeline.make_display_image(src)
        session = self._session_with_result(db, "uploads/expo/results/expo_9_ef.png")
        payload = service.serialize_session(db, session)
        result = payload["results"][0]
        assert result["image_url"] == "/uploads/expo/results/expo_9_ef.png"
        assert result["display_url"] == "/uploads/expo/results/expo_9_ef_disp.jpg"

    def test_display_url_none_for_legacy_result(self, db, tmp_path, monkeypatch):
        # 历史结果没有展示版：display_url 必须是 None（前端回退 image_url），不能造假路径
        monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
        session = self._session_with_result(db, "uploads/expo/results/legacy.png")
        payload = service.serialize_session(db, session)
        result = payload["results"][0]
        assert result["display_url"] is None
        assert result["image_url"] == "/uploads/expo/results/legacy.png"
