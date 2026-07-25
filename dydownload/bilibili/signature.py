"""WBI signature for Bilibili (B站) web APIs.

Reference: https://github.com/SocialSisterYi/bilibili-API-collect (WBI 签名).
The algorithm rotates 32 bytes of a static ``mixin_key`` table with values
derived from ``img_key`` + ``sub_key`` obtained via the ``/x/web-interface/nav``
endpoint, then signs the URL-encoded parameter string with that mix.
"""

from __future__ import annotations

import hashlib
import time
from urllib.parse import quote

# 32-byte index table for mixin_key rotation. Static (per upstream docs).
_MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 63, 36, 39, 56, 65, 53,
    31, 35, 27, 16, 23, 56, 9, 23, 64, 23, 51, 2, 56, 43, 12, 18,
]

# Characters that must be filtered from a value before URL-encoding.
_FILTER = "!'\()*"


def _filter_chars(s: str) -> str:
    """Strip characters that WBI signing considers unsafe in a value."""
    return "".join(c for c in s if c not in _FILTER)


def _wbi_mixin_key(img_key: str, sub_key: str) -> str:
    """Derive the 32-byte mixin key from img_key + sub_key."""
    raw = (img_key + sub_key)[:32]
    return "".join(raw[i] for i in _MIXIN_TABLE if i < len(raw))


def wbi_sign(params: dict, img_key: str, sub_key: str, *, wts: int | None = None) -> dict:
    """Sign ``params`` with WBI and return a new dict with ``wts`` + ``w_rid``.

    Args:
        params: Request parameters (will NOT be mutated).
        img_key: From ``/x/web-interface/nav`` → ``data.wbi_img.img_url``.
        sub_key: From ``/x/web-interface/nav`` → ``data.wbi_img.sub_url``.
        wts: Optional Unix-seconds timestamp; defaults to ``time.time()``.

    Returns:
        A new dict with signed params + ``wts`` + ``w_rid``.
    """
    signed = dict(params)
    signed["wts"] = int(wts if wts is not None else time.time())

    mixin_key = _wbi_mixin_key(img_key, sub_key)

    # Sort keys, URL-encode values (filtering unsafe chars), join with `&key=value`.
    pairs = []
    for key in sorted(signed.keys()):
        value = _filter_chars(str(signed[key]))
        pairs.append(f"{key}={quote(value, safe='')}")
    query = "&".join(pairs) + mixin_key

    signed["w_rid"] = hashlib.md5(query.encode("utf-8")).hexdigest()
    return signed
