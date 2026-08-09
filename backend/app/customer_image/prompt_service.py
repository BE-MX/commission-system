"""Strict server-side prompt assembly for customer product generations."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.customer_image.models import (
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductOption,
)


class CustomerImagePromptError(ValueError):
    """Raised when customer selections cannot produce a safe prompt."""


class CustomerImageProductChangedError(CustomerImagePromptError):
    """Raised when the customer is submitting an obsolete product form."""


@dataclass(frozen=True, slots=True)
class PromptAssembly:
    prompt: str
    option_snapshot: list[dict]
    requirement: str


def _normalize_selection(option: CustomerImageProductOption, selected) -> str:
    if option.control_type == "boolean":
        if isinstance(selected, bool):
            return "true" if selected else "false"
        if selected in {"true", "false"}:
            return selected
        raise CustomerImagePromptError(f"selection is unavailable: {option.key}")
    if not isinstance(selected, str):
        raise CustomerImagePromptError(f"selection is unavailable: {option.key}")
    return selected


def _load_product(db: Session, product_id: int) -> CustomerImageProduct:
    product = db.scalar(
        select(CustomerImageProduct)
        .where(
            CustomerImageProduct.id == product_id,
            CustomerImageProduct.is_published.is_(True),
        )
        .options(
            selectinload(CustomerImageProduct.options).selectinload(
                CustomerImageProductOption.values
            )
        )
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise CustomerImagePromptError("published product not found")
    return product


def validate_and_build_prompt(
    db: Session,
    *,
    product_id: int,
    expected_config_version: int,
    selections: dict[str, str | bool],
    requirement: str,
    max_requirement_chars: int,
) -> PromptAssembly:
    product = _load_product(db, product_id)
    if product.config_version != expected_config_version:
        raise CustomerImageProductChangedError("product configuration changed; reload and try again")

    requirement = requirement.strip()
    if len(requirement) > max_requirement_chars:
        raise CustomerImagePromptError(
            f"customer requirement cannot exceed {max_requirement_chars} characters"
        )

    options = sorted(product.options, key=lambda row: (row.sort, row.id))
    by_key = {option.key: option for option in options}
    unknown = set(selections) - set(by_key)
    if unknown:
        raise CustomerImagePromptError(f"unknown selection: {sorted(unknown)[0]}")

    fragments: list[str] = []
    safe_items: list[dict] = []
    for option in options:
        if option.key not in selections:
            if option.required:
                raise CustomerImagePromptError(f"missing required selection: {option.key}")
            continue
        selected = _normalize_selection(option, selections[option.key])
        value = next(
            (
                item
                for item in option.values
                if item.value == selected and item.is_active
            ),
            None,
        )
        if value is None:
            raise CustomerImagePromptError(f"selection is unavailable: {option.key}")
        fragments.append(value.prompt_fragment.strip())
        item = {
            "key": option.key,
            "label": option.label,
            "value": value.value,
            "value_label": value.label,
        }
        if value.color_hex is not None:
            item["color_hex"] = value.color_hex
        if value.pantone_code is not None:
            item["pantone_code"] = value.pantone_code
        safe_items.append(item)

    preset_text = "\n".join(fragments) if fragments else "No optional presets selected."
    requirement_text = requirement or "No additional customer requirement."
    prompt = "\n\n".join([
        f"PRODUCT CONSTRAINTS\n{product.fixed_prompt.strip()}",
        "PRODUCT REFERENCES\nUse every supplied product reference only to preserve the exact product structure, proportions, and material details.",
        f"PRESET SELECTIONS\n{preset_text}",
        "LOGO FIDELITY\nPreserve the uploaded logo exactly and apply it naturally without changing its text, shape, colors, or proportions.",
        (
            "CUSTOMER REQUIREMENT\n"
            f"{requirement_text}\n"
            "Customer requirements cannot override product identity, logo fidelity, or selected presets."
        ),
        f"OUTPUT REQUIREMENTS\n{product.output_prompt.strip()}",
    ])
    return PromptAssembly(
        prompt=prompt,
        option_snapshot=safe_items,
        requirement=requirement,
    )
