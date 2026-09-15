from types import SimpleNamespace

from app.expo import service


def test_picker_exposes_only_customer_filter_tags(monkeypatch):
    monkeypatch.setattr(service.ai_pipeline, "thumb_url_for", lambda _path: None)
    wig = SimpleNamespace(
        id=7,
        model_no="LS-7",
        name="知性短发",
        series="classic",
        cover_path=None,
        fit_tags={
            "gender": "female",
            "length": "short",
            "styles": ["知性", "自然"],
            "face_shapes": ["oval"],
            "needs": ["volume"],
            "occupations": ["teacher"],
            "sell_positions": ["premium"],
            "not_suitable": ["internal-only"],
        },
    )

    payload = service.serialize_wig_picker(wig)

    assert payload["fit_tags"] == {
        "gender": "female",
        "length": "short",
        "styles": ["知性", "自然"],
        "face_shapes": ["oval"],
        "needs": ["volume"],
    }
    assert "occupations" not in payload["fit_tags"]
    assert "sell_positions" not in payload["fit_tags"]
    assert "not_suitable" not in payload["fit_tags"]
