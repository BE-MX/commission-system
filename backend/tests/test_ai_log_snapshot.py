import json

from app.ai.log_snapshot import serialize_response_snapshot


def test_serialize_response_snapshot_omits_image_payloads():
    large_b64 = "a" * 90000
    snapshot = serialize_response_snapshot(
        {
            "data": [{"b64_json": large_b64}],
            "preview": f"data:image/png;base64,{large_b64}",
            "usage": {"total_tokens": 10},
        }
    )

    parsed = json.loads(snapshot)
    assert large_b64 not in snapshot
    assert parsed["data"][0]["b64_json"] == "[omitted base64 image, 90000 chars]"
    assert parsed["preview"] == "[omitted data image, 90022 chars]"
    assert parsed["usage"] == {"total_tokens": 10}
