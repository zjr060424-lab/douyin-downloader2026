"""HTTP client for Douyin API interactions."""

import random
from urllib.parse import urlencode

import httpx
from rich.console import Console

from dydownload.config import (
    API_HEADERS,
    BASE_HEADERS,
    DOUYIN_VIDEO_PAGE,
    DOUYIN_AWEME_DETAIL,
    IESDOUYIN_ITEM_INFO,
    IESDOUYIN_SHARE_PAGE,
    USER_AGENTS,
)
from dydownload.signature import extract_webid, sign_request

console = Console()


class DouyinAPIError(Exception):
    """Raised when a Douyin API call fails."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class CookieExpiredError(DouyinAPIError):
    """Raised when cookie has expired and user needs to refresh."""


class VideoNotFoundError(DouyinAPIError):
    """Raised when the video does not exist or has been deleted."""


class CaptchaError(DouyinAPIError):
    """Raised when Douyin returns a captcha challenge."""


def build_headers(cookie_string: str = "", referer: str = "") -> dict[str, str]:
    """Build HTTP headers with cookie and optional referer override."""
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(USER_AGENTS)
    if cookie_string:
        headers["Cookie"] = cookie_string
    if referer:
        headers["Referer"] = referer
    return headers


def resolve_short_link(short_url: str, cookie_string: str = "") -> str:
    """Resolve a v.douyin.com short link to the full video page URL.

    Douyin short links 302 redirect to the full /video/{id} page.
    We follow manually to extract the Location header.

    Returns the resolved full URL (e.g. https://www.douyin.com/video/{video_id}).
    Raises DouyinAPIError on failure.
    """
    headers = build_headers(cookie_string)

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=False) as client:
        try:
            response = client.get(short_url)
        except httpx.RequestError as e:
            raise DouyinAPIError(f"请求短链接失败: {e}") from e

        if response.status_code in (301, 302):
            location = response.headers.get("Location", "")
            if location:
                return location

        # If no redirect, check if we got a captcha page
        if response.status_code == 200:
            text = response.text
            if "验证" in text or "captcha" in text.lower():
                raise CaptchaError("抖音要求验证，请在浏览器中完成验证后重试", 200)

        raise DouyinAPIError(
            f"短链接解析失败 (HTTP {response.status_code})", response.status_code
        )


def fetch_video_page(video_id: str, cookie_string: str = "", debug: bool = False) -> str:
    """Fetch the Douyin video page HTML.

    The page contains embedded RENDER_DATA JSON with full video metadata.

    Raises CookieExpiredError if cookies are invalid.
    Raises VideoNotFoundError if the video doesn't exist.
    """
    url = DOUYIN_VIDEO_PAGE.format(video_id=video_id)
    referer = "https://www.douyin.com/"
    headers = build_headers(cookie_string, referer=referer)
    # Let httpx handle Accept-Encoding automatically
    headers.pop("Accept-Encoding", None)

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        try:
            response = client.get(url)
        except httpx.RequestError as e:
            raise DouyinAPIError(f"请求视频页面失败: {e}") from e

        if debug:
            console.print(f"[dim]请求 URL: {url}[/dim]")
            console.print(f"[dim]最终 URL: {response.url}[/dim]")
            console.print(f"[dim]HTTP 状态: {response.status_code}[/dim]")
            console.print(f"[dim]Content-Type: {response.headers.get('Content-Type', 'unknown')}[/dim]")
            console.print(f"[dim]Content-Encoding: {response.headers.get('Content-Encoding', 'none')}[/dim]")
            console.print(f"[dim]页面大小: {len(response.content)} bytes (raw)[/dim]")

        if response.status_code != 200:
            raise DouyinAPIError(
                f"视频页面请求失败 (HTTP {response.status_code})", response.status_code
            )

        text = response.text

        # Check for signs of cookie expiration
        if "passport" in str(response.url) or "login" in str(response.url):
            raise CookieExpiredError("Cookie 已过期，请在浏览器中刷新后重新推送")

        # Check for captcha
        if "验证" in text and "RENDER_DATA" not in text:
            raise CaptchaError("抖音要求验证，请在浏览器中完成验证后重试")

        # Check for deleted / private video
        if "视频不见了" in text or "视频已删除" in text or "该视频不存在" in text:
            raise VideoNotFoundError(f"视频不存在或已被删除 (video_id: {video_id})")

        if debug:
            has_render = "RENDER_DATA" in text
            has_router = "_ROUTER_DATA" in text or "routeData" in text.lower()
            has_server_data = "SERVER_DATA" in text or "serverData" in text.lower()
            console.print(f"[dim]RENDER_DATA 存在: {has_render}[/dim]")
            console.print(f"[dim]ROUTER_DATA/_TA 存在: {'_ROUTER_DATA' in text}[/dim]")
            # Save HTML for inspection
            import tempfile
            debug_path = tempfile.gettempdir() + "/dydownload_debug.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(text)
            console.print(f"[dim]HTML 已保存到: {debug_path}[/dim]")

        return text


def fetch_share_page(video_id: str, cookie_string: str = "", debug: bool = False) -> str:
    """Fetch the iesdouyin share page as an alternative data source.

    The share page sometimes has different rendering than douyin.com,
    and may contain embedded JSON data in a more accessible format.
    """
    url = IESDOUYIN_SHARE_PAGE.format(video_id=video_id)
    headers = build_headers(cookie_string)
    headers.pop("Accept-Encoding", None)
    # Mobile UA sometimes gets different (simpler) page
    headers["User-Agent"] = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    )

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        try:
            response = client.get(url)
        except httpx.RequestError as e:
            raise DouyinAPIError(f"请求分享页面失败: {e}") from e

        if debug:
            console.print(f"[dim]分享页 URL: {url}[/dim]")
            console.print(f"[dim]最终 URL: {response.url}[/dim]")
            console.print(f"[dim]HTTP 状态: {response.status_code}[/dim]")
            console.print(f"[dim]页面大小: {len(response.text)} chars[/dim]")

        if response.status_code != 200:
            raise DouyinAPIError(
                f"分享页面请求失败 (HTTP {response.status_code})", response.status_code
            )

        return response.text


def fetch_aweme_detail(
    video_id: str,
    cookie_string: str = "",
    webid: str = "",
    ms_token: str = "",
    user_agent: str = "",
) -> dict:
    """Call douyin.com aweme/detail API with a_bogus signature.

    Builds the complete query params (browser fingerprint, webid, msToken),
    generates the a_bogus signature, and calls the API.

    Returns the parsed JSON response on success.
    Raises DouyinAPIError on failure.
    """
    ua = user_agent or random.choice(USER_AGENTS)
    params = sign_request(
        aweme_id=video_id,
        user_agent=ua,
        webid=webid,
        ms_token=ms_token,
        cookie_str=cookie_string,
    )
    url = DOUYIN_AWEME_DETAIL
    referer = DOUYIN_VIDEO_PAGE.format(video_id=video_id)
    headers = dict(API_HEADERS)
    headers["User-Agent"] = ua
    headers["Referer"] = referer
    if cookie_string:
        headers["Cookie"] = cookie_string

    with httpx.Client(headers=headers, timeout=30.0) as client:
        try:
            response = client.get(url, params=params)
        except httpx.RequestError as e:
            raise DouyinAPIError(f"aweme/detail API 请求失败: {e}") from e

        if response.status_code != 200:
            raise DouyinAPIError(
                f"aweme/detail API 请求失败 (HTTP {response.status_code})",
                response.status_code,
            )

        try:
            data = response.json()
        except Exception as e:
            raise DouyinAPIError(f"aweme/detail API 返回格式异常: {e}") from e

        status_code = data.get("status_code", -1)
        if status_code != 0:
            status_msg = data.get("status_msg", "未知错误")
            raise DouyinAPIError(
                f"aweme/detail API 返回错误: {status_msg} ({status_code})"
            )

        aweme_detail = data.get("aweme_detail")
        if aweme_detail is None:
            filter_info = data.get("filter_detail", {})
            reason = filter_info.get("filter_reason", "未知原因")
            raise VideoNotFoundError(
                f"视频数据不可用 (filter_reason: {reason})"
            )

        return data


def fetch_item_info(video_id: str, cookie_string: str = "") -> dict:
    """Call iesdouyin iteminfo API as fallback data source.

    Returns the parsed JSON response.
    """
    params = {"item_ids": video_id}
    url = f"{IESDOUYIN_ITEM_INFO}?{urlencode(params)}"
    referer = DOUYIN_VIDEO_PAGE.format(video_id=video_id)
    headers = build_headers(cookie_string, referer=referer)
    headers["Accept"] = "application/json, text/plain, */*"

    with httpx.Client(headers=headers, timeout=30.0) as client:
        try:
            response = client.get(url)
        except httpx.RequestError as e:
            raise DouyinAPIError(f"API 请求失败: {e}") from e

        if response.status_code != 200:
            raise DouyinAPIError(
                f"API 请求失败 (HTTP {response.status_code})", response.status_code
            )

        try:
            data = response.json()
        except Exception as e:
            raise DouyinAPIError(f"API 返回格式异常: {e}") from e

        status_code = data.get("status_code", -1)
        if status_code != 0:
            status_msg = data.get("status_msg", "未知错误")
            raise DouyinAPIError(f"API 返回错误: {status_msg} ({status_code})")

        return data
