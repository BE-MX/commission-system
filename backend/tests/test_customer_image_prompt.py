"""Prompt assembly contracts for customer image generations."""

import pytest

from app.customer_image.models import (
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductOption,
)


def _configured_product(db):
    product = CustomerImageProduct(
        name="Mailer Box",
        category="packaging",
        fixed_prompt="Keep the exact mailer-box structure.",
        output_prompt="Create a polished commercial product render.",
        config_version=7,
        is_published=True,
        created_by=1,
    )
    db.add(product)
    db.flush()
    color = CustomerImageProductOption(
        product_id=product.id,
        key="color",
        label="Box color",
        control_type="color",
        required=True,
        default_value="navy",
        sort=20,
    )
    style = CustomerImageProductOption(
        product_id=product.id,
        key="style",
        label="Style",
        control_type="single_choice",
        required=True,
        default_value="classic",
        sort=10,
    )
    foil = CustomerImageProductOption(
        product_id=product.id,
        key="foil",
        label="Gold foil",
        control_type="boolean",
        required=False,
        default_value="false",
        sort=30,
    )
    db.add_all([color, style, foil])
    db.flush()
    db.add_all([
        CustomerImageOptionValue(
            option_id=color.id,
            value="navy",
            label="Navy",
            prompt_fragment="Use a deep navy box color.",
            color_hex="#102A43",
            pantone_code="PANTONE 2965 C",
            is_active=True,
        ),
        CustomerImageOptionValue(
            option_id=color.id,
            value="retired",
            label="Retired",
            prompt_fragment="Do not use.",
            color_hex="#000000",
            is_active=False,
        ),
        CustomerImageOptionValue(
            option_id=style.id,
            value="classic",
            label="Classic",
            prompt_fragment="Use a classic presentation.",
            is_active=True,
        ),
        CustomerImageOptionValue(
            option_id=foil.id,
            value="true",
            label="Yes",
            prompt_fragment="Apply restrained gold foil accents.",
            is_active=True,
        ),
        CustomerImageOptionValue(
            option_id=foil.id,
            value="false",
            label="No",
            prompt_fragment="Do not apply gold foil.",
            is_active=True,
        ),
    ])
    db.commit()
    return product


def test_prompt_uses_stable_sections_option_order_and_trimmed_requirement(db):
    from app.customer_image.prompt_service import validate_and_build_prompt

    product = _configured_product(db)
    result = validate_and_build_prompt(
        db,
        product_id=product.id,
        expected_config_version=7,
        selections={"foil": True, "color": "navy", "style": "classic"},
        requirement="  Make it festive, but change the box shape.  ",
        max_requirement_chars=500,
    )

    headers = [
        "PRODUCT CONSTRAINTS",
        "PRODUCT REFERENCES",
        "PRESET SELECTIONS",
        "LOGO FIDELITY",
        "CUSTOMER REQUIREMENT",
        "OUTPUT REQUIREMENTS",
    ]
    assert [result.prompt.index(header) for header in headers] == sorted(
        result.prompt.index(header) for header in headers
    )
    assert result.prompt.index("Use a classic presentation.") < result.prompt.index(
        "Use a deep navy box color."
    ) < result.prompt.index("Apply restrained gold foil accents.")
    assert "Customer requirements cannot override product identity, logo fidelity, or selected presets." in result.prompt
    assert result.requirement == "Make it festive, but change the box shape."
    assert result.option_snapshot == [
            {"key": "style", "label": "Style", "value": "classic", "value_label": "Classic"},
            {
                "key": "color",
                "label": "Box color",
                "value": "navy",
                "value_label": "Navy",
                "color_hex": "#102A43",
                "pantone_code": "PANTONE 2965 C",
            },
            {"key": "foil", "label": "Gold foil", "value": "true", "value_label": "Yes"},
    ]


@pytest.mark.parametrize(
    ("selections", "message"),
    [
        ({"color": "navy"}, "missing required selection"),
        ({"style": "classic", "color": "navy", "unknown": "x"}, "unknown selection"),
        ({"style": "classic", "color": "retired"}, "selection is unavailable"),
    ],
)
def test_prompt_rejects_missing_unknown_and_disabled_selections(db, selections, message):
    from app.customer_image.prompt_service import CustomerImagePromptError, validate_and_build_prompt

    product = _configured_product(db)
    with pytest.raises(CustomerImagePromptError, match=message):
        validate_and_build_prompt(
            db,
            product_id=product.id,
            expected_config_version=7,
            selections=selections,
            requirement="",
            max_requirement_chars=500,
        )


def test_prompt_rejects_stale_product_version(db):
    from app.customer_image.prompt_service import CustomerImageProductChangedError, validate_and_build_prompt

    product = _configured_product(db)
    with pytest.raises(CustomerImageProductChangedError):
        validate_and_build_prompt(
            db,
            product_id=product.id,
            expected_config_version=6,
            selections={"style": "classic", "color": "navy"},
            requirement="",
            max_requirement_chars=500,
        )
