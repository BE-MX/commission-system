"""expo 图片压缩链路测试（2026-07-14 网络拥堵治理）。

覆盖三块：
- downscale_inplace：上传落盘即压（超边长才动、保持扩展名、失败不阻断）
- make_display_image / display_rel_for：结果图 kiosk 展示版的生成与探测
- serialize_session：display_url 契约（有展示版给压缩 URL，历史结果回退 None）
"""

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
