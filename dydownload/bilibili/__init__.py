"""Bilibili (B站) video download support for dydownload.

This subpackage implements B站-specific HTTP / signing / parsing, and
exposes a small public API (see __all__) consumed by ``dydownload.pipeline``.
The dispatcher's auto-routing picks this module when a URL points to
bilibili.com or b23.tv.
"""

from dydownload.bilibili.api_client import (
    BilibiliAPIError,
    BilibiliCookieExpiredError,
    BilibiliNotFoundError,
    BangumiNotSupportedError,
    build_headers,
    extract_av,
    extract_bv,
    fetch_playurl,
    fetch_view,
    fetch_wbi_keys,
    is_bangumi_url,
    pick_streams,
    probe_cookie,
    resolve_short_link,
)
from dydownload.bilibili.signature import wbi_sign
from dydownload.bilibili.video_parser import MediaInfo, PageInfo, StreamPlan, parse_view

__all__ = [
    "BilibiliAPIError",
    "BilibiliCookieExpiredError",
    "BilibiliNotFoundError",
    "BangumiNotSupportedError",
    "build_headers",
    "extract_av",
    "extract_bv",
    "fetch_playurl",
    "fetch_view",
    "fetch_wbi_keys",
    "is_bangumi_url",
    "pick_streams",
    "probe_cookie",
    "resolve_short_link",
    "MediaInfo",
    "PageInfo",
    "StreamPlan",
    "parse_view",
    "wbi_sign",
]
