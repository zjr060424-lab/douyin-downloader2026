"""Cookie loading, validation, and expiration detection."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx

from dydownload.config import COOKIE_FILE, KEY_COOKIE_NAMES, LOCAL_SERVER_HOST, LOCAL_SERVER_PORT, BASE_HEADERS


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


def load_cookies() -> CookieInfo:
    """Load cookies from file and validate structure.

    Returns CookieInfo with status indicating whether key cookies are present.
    Does NOT validate freshness (that requires a network probe).
    """
    if not COOKIE_FILE.exists():
        return CookieInfo(
            status=CookieStatus.MISSING,
            cookie_string="",
            missing_keys=list(KEY_COOKIE_NAMES),
        )

    cookie_string = COOKIE_FILE.read_text(encoding="utf-8").strip()
    if not cookie_string:
        return CookieInfo(
            status=CookieStatus.MISSING,
            cookie_string="",
            missing_keys=list(KEY_COOKIE_NAMES),
        )

    # Parse key cookies from the string
    key_cookies = {}
    for pair in cookie_string.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, _, value = pair.partition("=")
            if name.strip() in KEY_COOKIE_NAMES:
                key_cookies[name.strip()] = value.strip()

    missing_keys = [k for k in KEY_COOKIE_NAMES if k not in key_cookies]

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


def probe_cookie_freshness(cookie_string: str, timeout: float = 10.0) -> CookieStatus:
    """Check if cookies are still valid by making a probe request to douyin.com.

    If the response redirects to a login/passport page, the session is expired.
    """
    headers = dict(BASE_HEADERS)
    headers["Cookie"] = cookie_string

    try:
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as client:
            response = client.get("https://www.douyin.com/")

            # If redirected to passport/login, cookie is expired
            if response.status_code in (301, 302):
                location = response.headers.get("Location", "")
                if "passport" in location or "login" in location:
                    return CookieStatus.EXPIRED

            if response.status_code == 200:
                text = response.text
                # No RENDER_DATA + login-related content = likely expired
                if "RENDER_DATA" not in text and ("passport" in text or "login" in text):
                    return CookieStatus.EXPIRED
                return CookieStatus.VALID

            return CookieStatus.UNKNOWN

    except httpx.RequestError:
        return CookieStatus.UNKNOWN
