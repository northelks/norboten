"""The signature on a rated attempt's fact record — docs/lab-spec.md section 13.

HMAC-SHA256 over the record's canonical JSON, under the attempt's key. The guest signs with it and
the server verifies with it; both import this module, so the two can never disagree about what
"canonical" means.
"""

from __future__ import annotations

import hashlib
import hmac
import json


def canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(key_hex: str, record: dict) -> str:
    return hmac.new(bytes.fromhex(key_hex), canonical(record), hashlib.sha256).hexdigest()


def verify(key_hex: str, record: dict, signature: str) -> bool:
    try:
        expected = sign(key_hex, record)
    except ValueError:  # a malformed key
        return False
    return hmac.compare_digest(expected, str(signature))
