"""Canonical JSON — THE single serialization used for hashing, snapshots,
and packet checksums (specs/11 §4.1, FR-AUD-7).

Rules: UTF-8; keys sorted lexicographically at every level; compact
separators; Decimal serialized as its exact str() form; no NaN/Inf;
arrays order-preserving. Divergent implementations are the classic
hash-mismatch bug — there must be exactly one (this one).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def _normalize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, float):
        raise TypeError("float is forbidden in audited payloads (NFR-2)")
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(
        _normalize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["canonical_json", "sha256_hex"]
