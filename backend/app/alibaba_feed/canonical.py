"""Strict JSON transport decoding and the v1 semantic digest."""
import hashlib
import json

from .errors import FeedError


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_number(value):
        raise ValueError("integer numbers only")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_float=reject_number, parse_constant=reject_number)
        stack = [(value, 1)]
        while stack:
            node, depth = stack.pop()
            if depth > 32:
                raise ValueError("depth")
            if isinstance(node, dict):
                stack.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                stack.extend((child, depth + 1) for child in node)
        canonical_bytes(value)  # Reject lone Unicode surrogates, including in keys.
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise FeedError(400, "MALFORMED_JSON") from None
