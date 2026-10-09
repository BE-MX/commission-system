import copy
import secrets

import pytest
from cryptography.exceptions import InvalidTag

from app.portal.errors import PortalError
from app.portal.mapping import project_mapping
from app.portal.security import (csrf_token, keyed_digest, new_token, open_secret,
    require_origin, seal_secret, token_digest, verify_csrf)


def test_credentials_are_random_and_server_keeps_only_digest():
    first, second = new_token(), new_token()
    assert first != second and len(first) >= 43
    assert token_digest(first) != first and len(token_digest(first)) == 64


def test_otp_is_bound_to_email_purpose_and_challenge():
    key = secrets.token_hex(32)
    original = keyed_digest(key, "challenge-a", "123456", "a@example.com", "login")
    assert original != keyed_digest(key, "challenge-b", "123456", "a@example.com", "login")
    assert original != keyed_digest(key, "challenge-a", "123456", "b@example.com", "login")
    assert original != keyed_digest(key, "challenge-a", "123456", "a@example.com", "activate")
    assert keyed_digest(key, "a", "bc") != keyed_digest(key, "ab", "c")


def test_csrf_is_not_reusable_across_sessions():
    key, nonce = secrets.token_hex(32), secrets.token_hex(32)
    token = csrf_token(key, "session-a", nonce)
    verify_csrf(key, "session-a", nonce, token)
    with pytest.raises(PortalError):
        verify_csrf(key, "session-b", nonce, token)
    with pytest.raises(PortalError) as error:
        verify_csrf(key, "session-a", nonce, "é")
    assert error.value.status == 403


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "https://shop.example.evil.test", "https://shop.example/"])
def test_origin_comparison_is_exact(origin):
    with pytest.raises(PortalError):
        require_origin(origin, "https://shop.example")


def test_mail_secret_is_authenticated_and_bound_to_one_event():
    key = secrets.token_hex(32)
    context = dict(event_key="invite:1", purpose="activate", object_id="invitation-1")
    secret = new_token()
    encrypted = seal_secret(key, secret, **context)
    assert secret.encode() not in encrypted
    assert open_secret(key, encrypted, **context) == secret
    with pytest.raises(InvalidTag):
        open_secret(key, encrypted, **dict(context, event_key="invite:2"))
    with pytest.raises(InvalidTag):
        open_secret(key, encrypted[:-1] + bytes([encrypted[-1] ^ 1]), **context)


def catalog():
    return [dict(item_id="a", model_key="weft", color_key="shade-1", model_name="Standard Weft",
                 color_name="1", length="18", weight="20", unit="piece", product_kind="hair"),
            dict(item_id="b", model_key="weft", color_key="shade-2", model_name="Standard Weft",
                 color_name="2", length="22", weight="20", unit="piece", product_kind="hair")]


def test_customer_mapping_leaves_standard_catalog_unchanged():
    items = catalog()
    original = copy.deepcopy(items)
    result = project_mapping(items, [dict(kind="model", source_key="weft", display_value="Signature Weft"),
                                    dict(kind="color", source_key="shade-1", display_value="Mushroom Melt")])
    assert result[0]["model_name"] == "Signature Weft"
    assert result[0]["color_name"] == "Mushroom Melt"
    assert items == original


def test_same_shade_across_lengths_is_valid():
    items = catalog()
    items[1]["color_key"] = "shade-1"
    assert len(project_mapping(items, [dict(kind="color", source_key="shade-1", display_value="Natural")])) == 2


def test_two_different_shades_cannot_hide_behind_different_lengths():
    entries = [dict(kind="color", source_key=key, display_value="Natural") for key in ["shade-1", "shade-2"]]
    with pytest.raises(PortalError) as error:
        project_mapping(catalog(), entries)
    assert error.value.code == "MAPPING_CONFLICT"


def test_different_models_with_same_customer_name_still_detect_shade_conflict():
    items = catalog()
    items[1]["model_key"] = "another-standard-model"
    entries = [dict(kind="model", source_key=key, display_value="Weft") for key in ["weft", "another-standard-model"]]
    entries += [dict(kind="color", source_key=key, display_value="Natural") for key in ["shade-1", "shade-2"]]
    with pytest.raises(PortalError) as error:
        project_mapping(items, entries)
    assert error.value.code == "MAPPING_CONFLICT"


def test_customer_sku_conflict_uses_unicode_normalization():
    entries = [dict(kind="sku", source_key="a", item_id="a", display_value="Weft", customer_sku="SKU 1"),
               dict(kind="sku", source_key="b", item_id="b", display_value="Weft", customer_sku="ＳＫＵ １")]
    with pytest.raises(PortalError):
        project_mapping(catalog(), entries)


@pytest.mark.parametrize("label", ["", "<img onerror=x>", "shade\n2", "x" * 129, "a\u200bb"])
def test_mapping_is_plain_bounded_text(label):
    with pytest.raises(PortalError):
        project_mapping(catalog(), [dict(kind="color", source_key="shade-1", display_value=label)])


def test_mapping_cannot_reference_another_customers_catalog():
    with pytest.raises(PortalError) as error:
        project_mapping(catalog(), [dict(kind="sku", source_key="hidden", item_id="hidden", display_value="Weft")])
    assert error.value.status == 404


@pytest.mark.parametrize("kind,field", [("model","display_value"),("color","display_value"),("sku","display_value"),("sku","customer_sku")])
@pytest.mark.parametrize("label", ["＜img src=x onerror=alert(1)＞", "﹤script﹥alert(1)﹤/script﹥", "ﷺ" * 12])
def test_normalized_mapping_markup_or_expansion_is_rejected(kind, field, label):
    entry = dict(kind=kind, source_key={"model":"weft","color":"shade-1","sku":"a"}[kind], display_value="Plain label")
    if kind == "sku": entry["item_id"] = "a"
    entry[field] = label
    with pytest.raises(PortalError) as caught:
        project_mapping(catalog(), [entry])
    assert caught.value.code == "INVALID_INPUT" and caught.value.status == 422


def test_normalized_mapping_preserves_plain_multilingual_labels_and_literal_quotes():
    result = project_mapping(catalog(), [dict(kind="sku",source_key="a",item_id="a",
        display_value='Ｓｉｌｋ " & 莱莎',customer_sku='=ＨＹＰＥＲＬＩＮＫ("example.test","SKU")')])
    assert result[0]["model_name"] == 'Silk " & 莱莎'
    assert result[0]["customer_sku"] == '=HYPERLINK("example.test","SKU")'
