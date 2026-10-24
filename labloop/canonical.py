"""Canonical serialisation and content digests.

Vendored from persistentepiphany/ppi-harness, harness/canonical.py at commit
0d256734. A parsed document is reduced to one byte sequence that depends on its
content and not on its formatting, so a frozen plan keeps its digest when its
keys are reordered and loses it when any value changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_FORM = "json-sorted-keys-utf8-compact/v1"


def canonical_bytes(document: Any) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_document(document: Any) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
