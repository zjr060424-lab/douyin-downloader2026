"""Cookie loading, validation, and expiration detection (Douyin + Bilibili)."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

import httpx

from dydownload.config import (
    BASE_HEADERS,
    BILI_COOKIE_FILE,
    COOKIE_FILE,
    KEY_COOKIE_NAMES,
    KEY_COOKIE_NAMES_BILI,
    LOCAL_SERVER_HOST,
    LOCAL_SERVER_PORT,
)


class CookieStatus(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass
class CookieInfo:
    status: CookieStatus
    cookie_string: str
    key_cookies: dict[str, str] = field(default_factory=dict)
    missing_keys: list[str] = field(default_factory=list)


_PLATFORMS = Literal["douyin", "bilibili"]

_PLATFORM_FILES = {
    "douyin": COOKIE_FILE,
    "bilibili": BILI_COOKIE_FILE,
}

_PLATFORM_KEYS = {
    "douyin": KEY_COOKIE_NAMES,
    "bilibili": KEY_COOKIE_NAMES_BILI,
}


def _load_cookies_for_platform(platform: str) -> CookieInfo:
    """Internal: load the cookie file for ``platform`` and check key fields."""
    path = _PLATFORM_FILES[platform]
    keys = _PLATFORM_KEYS[platform]
    if not path.exists():
        return CookieInfo(
            status=CookieStatus.MISSING,
            cookie_string="",
            missing_keys=list(keys),
        )
    cookie_string = path.read_text(encoding="utf-8").strip()
    if not cookie_string:
        return CookieInfo(
            status=CookieStatus.MISSING,
            cookie_string="",
            missing_keys=list(keys),
        )
    key_cookies = {}
    for pair in cookie_string.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, _, value = pair.partition("=")
            if name.strip() in keys:
                key_cookies[name.strip()] = value.strip()
    missing_keys = [k for k in keys if k not in key_cookies]
    if missing_keys:
        return CookieInfo(
            status=CookieStatus.MISSING,
            cookie_string=cookie_string,
            key_cookies=key_cookies,
            missing_keys=missing_keys,
        )
    return CookieInfo(
        status=CookieStatus.UNKNOWN,
        cookie_string=cookie_string,
        key_cookies=key_cookies,
    )


def load_cookies() -> CookieInfo:
    """Load Douyin cookies. (Backwards-compatible — picks the existing file.)"""
    return _load_cookies_for_platform("douyin")


def load_bilibili_cookies() -> CookieInfo:
    """Load Bilibili cookies from their separate file."""
    return _load_cookies_for_platform("bilibili")


def probe_cookie_freshness(
    cookie_string: str,
    timeout: float = 10.0,
    platform: str = "douyin",
) -> CookieStatus:
    """Probe whether the cookie blob is still logged in.

    For ``"douyin"`` (default): a cheap HEAD/GET to ``https://www.douyin.com/``;
    expired if redirected to ``passport`` or login shell.

    For ``"bilibili"``: hits ``/x/web-interface/nav`` and considers VALID iff
    ``code==0`` and the key query succeeds (gives us ``SESSDATA`` round-trip).
    """
    if not cookie_string:
        return CookieStatus.MISSING

    if platform == "bilibili":
        try:
            from dydownload.bilibili.api_client import probe_cookie
            return (
                CookieStatus.VALID
                if probe_cookie(cookie_string)
                else CookieStatus.EXPIRED
            )
        except httpx.RequestError:
            return CookieStatus.UNKNOWN
        except Exception:
            return CookieStatus.EXPIRED

    # Douyin probe (original logic)
    headers = dict(BASE_HEADERS)
    headers["Cookie"] = cookie_string
    try:
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as client:
            response = client.get("https://www.douyin.com/")
            if response.status_code in (301, 302):
                location = response.headers.get("Location", "")
                if "passport" in location or "login" in location:
                    return CookieStatus.EXPIRED
            if response.status_code == 200:
                text = response.text
                if "RENDER_DATA" not in text and ("passport" in text or "login" in text):
                    return CookieStatus.EXPIRED
                return CookieStatus.VALID
            return CookieStatus.UNKNOWN
    except httpx.RequestError:
        return CookieStatus.UNKNOWN
