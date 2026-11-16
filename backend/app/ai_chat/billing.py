"""Explicitly configured token-price estimates; never infer vendor prices."""
from decimal import Decimal, InvalidOperation


def pricing_options(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'currency', 'input_per_million', 'output_per_million'}:
        raise ValueError('价格需包含币种、每百万输入和输出 token 价格')
    if not isinstance(value['currency'], str) or value['currency'] not in {'CNY', 'USD'}:
        raise ValueError('计价币种只支持 CNY 或 USD')
    result = {'currency': value['currency']}
    for key in ('input_per_million', 'output_per_million'):
        try:
            if isinstance(value[key], bool):
                raise ValueError('invalid price')
            number = Decimal(str(value[key]))
            if not number.is_finite() or not 0 <= number <= 1_000_000 or number.as_tuple().exponent < -6:
                raise ValueError('invalid price')
        except (ValueError, InvalidOperation):
            raise ValueError('token 单价应为 0–1000000，最多六位小数') from None
        result[key] = str(number)
    return result


def estimate_cost(pricing, input_tokens, output_tokens):
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    if input_tokens < 0 or output_tokens < 0:
        return None
    return (Decimal(str(pricing['input_per_million'])) * input_tokens
            + Decimal(str(pricing['output_per_million'])) * output_tokens) / 1_000_000
