from app.color import calc_service
from app.color.models import PantoneReference


def test_nearest_pantone_keeps_tcx_matching_when_coated_is_closer(db):
    target = "#FFFFFF"
    target_lab = calc_service.rgb_to_lab(calc_service.hex_to_rgb(target))
    db.add(PantoneReference(
        pantone_code="11-0601 TCX",
        hex_code="#F4F5F0",
        rgb_r=244,
        rgb_g=245,
        rgb_b=240,
        lab_l=float(target_lab[0] - 10),
        lab_a=float(target_lab[1]),
        lab_b_val=float(target_lab[2]),
        collection="tcx",
    ))
    db.add(PantoneReference(
        pantone_code="White C",
        hex_code=target,
        rgb_r=255,
        rgb_g=255,
        rgb_b=255,
        lab_l=float(target_lab[0]),
        lab_a=float(target_lab[1]),
        lab_b_val=float(target_lab[2]),
        collection="coated",
    ))
    db.commit()

    result = calc_service.find_nearest_pantone(target, db)

    assert result["pantone_code"] == "11-0601 TCX"
