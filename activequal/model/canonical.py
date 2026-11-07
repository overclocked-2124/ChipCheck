"""RFC 8785 JSON Canonicalization Scheme and the contract hash (HLD 04 §12, HLD 10 WP1).

Dependency-free. Numbers follow the ECMAScript Number-to-string algorithm (shortest round-trip
digits, JS exponent format), strings use the minimal RFC 8785 §3.2.2.2 escaping, and object keys
sort by UTF-16 code units. Integers beyond 2**53 are rejected because JSON consumers on JavaScript
cannot represent them exactly; NaN, infinities, non-string keys and unsupported types are rejected.
"""

from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from typing import Any

MAX_SAFE_INT = 2 ** 53
MAX_DEPTH = 100


class CanonicalError(ValueError):
    """The value has no RFC 8785 canonical form."""


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalError("NaN and infinity cannot be canonicalized")
    if value == 0:
        return "0"   # also -0.0
    sign = "-" if value < 0 else ""
    _, digit_tuple, exponent = Decimal(repr(abs(value))).as_tuple()
    digits = "".join(map(str, digit_tuple))
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)   # value = int(stripped) * 10**exponent
    digits = stripped
    k = len(digits)
    n = k + exponent   # value = 0.digits * 10**n, the "n" of ECMAScript 262 Number::toString
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _string(value: str) -> str:
    out = ['"']
    for char in value:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif char < " ":
            out.append(f"\\u{ord(char):04x}")
        elif "\ud800" <= char <= "\udfff":
            raise CanonicalError("strings with lone surrogates cannot be encoded")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _encode(value: Any, depth: int) -> str:
    if depth > MAX_DEPTH:
        raise CanonicalError("value is nested too deeply")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalError("integers beyond 2**53 are not exactly representable in JSON consumers")
        return str(int(value))
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalError("object keys must be strings")
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(f"{_string(key)}:{_encode(item, depth + 1)}" for key, item in items) + "}"
    raise CanonicalError(f"unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    return _encode(value, 0).encode("utf-8")


def contract_hash(contract: dict[str, Any]) -> str:
    """Lowercase hex SHA-256 of the contract's RFC 8785 canonical form."""
    return hashlib.sha256(canonical_json(contract)).hexdigest()
