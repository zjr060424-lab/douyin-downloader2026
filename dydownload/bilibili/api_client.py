"""Bilibili API HTTP client + WBI-fetching helpers."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from dydownload.bilibili.signature import wbi_sign

# Endpoints
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
PLAYURL_URL = "https://api.bilibili.com/x/player/playurl"


# ── Exceptions ─────────────────────────────────────────────────────────────


class BilibiliAPIError(Exception):
    """Raised when a B站 API call fails."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class BilibiliCookieExpiredError(BilibiliAPIError):
    """Raised when the SESSDATA is missing / expired."""


class BilibiliNotFoundError(BilibiliAPIError):
    """Raised when the requested BV/AV does not exist or is private."""


class BangumiNotSupportedError(BilibiliAPIError):
    """Raised on bangumi URLs — explicit "out of scope" rather than ambiguous."""


# ── Headers ────────────────────────────────────────────────────────────────


# A reasonable PC UA — bilibili checks UA string and rejects with 412 when
# missing. We don't randomise per request (small load on each download is OK).
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def build_headers(cookie_string: str = "", user_agent: str = "", referer: str = "") -> dict:
    """Build HTTP headers for B站 API calls."""
    # httpx enforces ASCII for header values; sanitise defensively so callers
    # that pass raw shared-text blobs (with Chinese titles) don't crash.
    headers = {
        "User-Agent": user_agent or _DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer or "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    headers = {k: _safe_str(v) for k, v in headers.items()}
    if cookie_string:
        headers["Cookie"] = cookie_string
    return headers


# ── URL helpers ────────────────────────────────────────────────────────────


_BV_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")
_AV_PATTERN = re.compile(r"(?:^|/|\?)av(\d+)", re.IGNORECASE)
_BANGUMI_PATTERN = re.compile(r"(?:bangumi\.bilibili\.com|/bangumi/play/(?:ep|ss)\d+)", re.IGNORECASE)


def extract_bv(url: str) -> str:
    """Pull a BV id from a bilibili.com video URL, or '' if none."""
    m = _BV_PATTERN.search(url)
    return m.group(0) if m else ""


def extract_av(url: str) -> str:
    """Pull a numeric av id from a URL, or '' if none."""
    m = _AV_PATTERN.search(url)
    return m.group(1) if m else ""


def is_bangumi_url(url: str) -> bool:
    return bool(_BANGUMI_PATTERN.search(url))


def resolve_short_link(url: str, cookie_string: str = "", user_agent: str = "") -> str:
    """Follow a b23.tv redirect chain to the canonical page."""
    headers = build_headers(cookie_string, user_agent)
    current = url
    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=False) as client:
        for _ in range(5):
            if "b23.tv" not in current:
                return current
            try:
                response = client.get(current)
            except httpx.RequestError:
                break
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            location = response.headers.get("Location", "")
            if not location:
                break
            current = urljoin(current, location)
    return current


# ── WBI key retrieval ─────────────────────────────────────────────────────


def _fetch_nav(cookie_string: str = "", user_agent: str = "") -> dict:
    """Return a validated `/nav` response payload."""
    headers = build_headers(cookie_string, user_agent)
    with httpx.Client(headers=headers, timeout=15.0) as client:
        try:
            response = client.get(NAV_URL)
        except httpx.RequestError as exc:
            # str(exc) may itself raise UnicodeEncodeError on Windows frozen
            # builds if the underlying message contains non-ASCII characters.
            # Coerce to a sanitised string before composing the BilibiliAPIError.
            raise BilibiliAPIError(
                "nav 接口请求失败: {}".format(_safe_str(exc))
            ) from exc
    if response.status_code != 200:
        raise BilibiliAPIError(
            "nav 接口 HTTP {}".format(response.status_code),
            code=response.status_code,
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise BilibiliAPIError(
            "nav 接口返回非 JSON: {}".format(_safe_str(exc))
        ) from exc
    code = payload.get("code")
    if code != 0:
        message = payload.get("message", "未知错误")
        raise BilibiliAPIError(
            "nav 接口返回错误: {} ({})".format(_safe_str(message), code),
            code=code,
        )
    return payload


def _safe_str(obj) -> str:
    """Return ``str(obj)`` with non-ASCII bytes replaced — defensive helper to
    avoid UnicodeEncodeError on Windows frozen builds when ``str()`` produces
    a string with characters outside the system code page."""
    try:
        s = str(obj)
    except Exception:
        return "<unprintable>"
    return s.encode("ascii", errors="replace").decode("ascii")


def fetch_wbi_keys(cookie_string: str = "", user_agent: str = "") -> tuple[str, str]:
    """Hit /x/web-interface/nav to get the live WBI img_key/sub_key."""
    data = _fetch_nav(cookie_string, user_agent)
    wbi_img = (data.get("data") or {}).get("wbi_img") or {}
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    img_key = urlparse(img_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    sub_key = urlparse(sub_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if not (img_key and sub_key):
        raise BilibiliAPIError("nav 接口未返回 WBI keys（可能被风控）")
    return img_key, sub_key


# ── /view ──────────────────────────────────────────────────────────────────


def fetch_view(
    url_or_bvid: str,
    cookie_string: str = "",
    user_agent: str = "",
) -> dict:
    """Fetch the ``/x/web-interface/view`` JSON for a regular video URL.

    Performs one /nav to obtain WBI keys (cached internally later by callers),
    then signs ``/view`` params with wts + w_rid.

    Returns the parsed JSON dict (with top-level ``code``/``data``).
    Raises BilibiliCookieExpiredError / BilibiliNotFoundError / BilibiliAPIError.
    """
    bv = extract_bv(url_or_bvid)
    av = extract_av(url_or_bvid)
    if not (bv or av):
        raise BilibiliAPIError(
            "无法从 URL 提取 BV/AV id: {}".format(_safe_str(url_or_bvid))
        )

    img_key, sub_key = fetch_wbi_keys(cookie_string, user_agent)

    params: dict[str, str] = {}
    if bv:
        params["bvid"] = bv
    else:
        params["aid"] = av

    signed = wbi_sign(params, img_key, sub_key)
    # Header values must be ASCII — extract a clean URL to use as Referer.
    # ``url_or_bvid`` may be a shared-text blob like "【中文标题】 https://...BV.."
    # whose non-ASCII prefix would break httpx's _normalize_header_value.
    referer = (
        "https://www.bilibili.com/video/" + (bv or "av" + av)
        if bv or av else url_or_bvid
    )
    headers = build_headers(cookie_string, user_agent, referer=referer)
    with httpx.Client(headers=headers, timeout=20.0) as c:
        try:
            r = c.get(VIEW_URL, params=signed)
        except httpx.RequestError as e:
            raise BilibiliAPIError(
                "view 接口请求失败: {}".format(_safe_str(e))
            ) from e
    if r.status_code != 200:
        raise BilibiliAPIError(
            "view 接口 HTTP {}".format(r.status_code), code=r.status_code
        )
    try:
        data = r.json()
    except Exception as e:
        raise BilibiliAPIError(
            "view 接口返回非 JSON: {}".format(_safe_str(e))
        ) from e

    code = data.get("code")
    if code == -101:
        raise BilibiliCookieExpiredError("B站 Cookie 缺失或已过期，请重新登录并推送")
    if code == -404:
        raise BilibiliNotFoundError(
            "视频不存在 (BV/AV: {})".format(_safe_str(bv) or "av" + _safe_str(av)),
            code=code,
        )
    if code != 0:
        msg = data.get("message", "未知错误")
        raise BilibiliAPIError(
            "view 接口错误: {} ({})".format(_safe_str(msg), code), code=code
        )

    return data


# ── /playurl ───────────────────────────────────────────────────────────────


def fetch_playurl(
    bvid: str,
    cid: int,
    cookie_string: str = "",
    user_agent: str = "",
    *,
    qn: int = 80,
    fnval: int = 16,    # 16 = DASH (1 = MP4 legacy)
    fnver: int = 0,
    fourk: int = 1,
) -> dict:
    """Fetch the ``/x/player/playurl`` JSON for a specific page.

    qn quality codes:
        16=360p, 32=480p, 64=720p, 80=1080p, 112=1080p+, 116=1080p60, 120=4K
    """
    params = {
        "bvid": bvid,
        "cid": str(cid),
        "qn": str(qn),
        "fnval": str(fnval),
        "fnver": str(fnver),
        "fourk": str(fourk),
        "platform": "html5",
        "high_quality": "1",
    }
    headers = build_headers(
        cookie_string, user_agent,
        referer="https://www.bilibili.com/video/{}".format(_safe_str(bvid)),
    )
    with httpx.Client(headers=headers, timeout=20.0) as c:
        try:
            r = c.get(PLAYURL_URL, params=params)
        except httpx.RequestError as e:
            raise BilibiliAPIError(
                "playurl 接口请求失败: {}".format(_safe_str(e))
            ) from e
    if r.status_code != 200:
        raise BilibiliAPIError(
            "playurl 接口 HTTP {}".format(r.status_code), code=r.status_code
        )
    try:
        data = r.json()
    except Exception as e:
        raise BilibiliAPIError(
            "playurl 接口非 JSON: {}".format(_safe_str(e))
        ) from e

    code = data.get("code")
    if code == -101:
        raise BilibiliCookieExpiredError("B站 Cookie 过期，请重新登录并推送")
    if code == -404:
        raise BilibiliNotFoundError(
            "分 P 不存在 (cid={})".format(cid), code=code
        )
    if code != 0:
        msg = data.get("message", "未知错误")
        raise BilibiliAPIError(
            "playurl 接口错误: {} ({})".format(_safe_str(msg), code), code=code
        )
    return data


# ── Cookie probe ──────────────────────────────────────────────────────────


def probe_cookie(cookie_string: str, user_agent: str = "") -> bool:
    """Return True only when `/nav` confirms the session is logged in."""
    if not cookie_string or "SESSDATA=" not in cookie_string:
        return False
    try:
        payload = _fetch_nav(cookie_string, user_agent)
    except BilibiliAPIError:
        return False
    return (payload.get("data") or {}).get("isLogin") is True


# ── Stream picker ─────────────────────────────────────────────────────────


def pick_streams(playurl_data: dict, *, prefer_dash: bool = True, qn: int = 80):
    """Return a dict describing what to download given a /playurl response.

    Returns one of:
        {"kind": "dash", "video_url": ..., "audio_url": ..., "quality": N,
         "width": int, "height": int, "duration": int}
        {"kind": "single", "url": ..., "quality": N, "width": int, "height": int,
         "duration": int}
        None  (no usable stream)
    """
    inner = (playurl_data or {}).get("data") or {}
    dash = inner.get("dash") or {}
    durl = inner.get("durl") or []

    quality = inner.get("quality")
    width = inner.get("width")
    height = inner.get("height")
    duration = inner.get("timelength", 0)

    if prefer_dash and dash:
        v_list = dash.get("video") or []
        a_list = dash.get("audio") or []
        # Highest-quality video stream
        if v_list:
            v_list = sorted(v_list, key=lambda x: x.get("id", 0), reverse=True)
            video_url = (v_list[0].get("baseUrl") or v_list[0].get("base_url") or
                         v_list[0].get("url"))
            audio_url = ""
            if a_list:
                a_list = sorted(a_list, key=lambda x: x.get("id", 0), reverse=True)
                audio_url = (a_list[0].get("baseUrl") or a_list[0].get("base_url") or
                             a_list[0].get("url"))
            return {
                "kind": "dash",
                "video_url": video_url,
                "audio_url": audio_url,
                "quality": v_list[0].get("id"),
                "width": width,
                "height": height,
                "duration": duration,
            }

    if durl:
        d0 = durl[0]
        url = d0.get("url") or ""
        if url:
            return {
                "kind": "single",
                "url": url,
                "quality": quality,
                "width": width,
                "height": height,
                "duration": duration,
            }

    return None
