"""Extract video info from Douyin page HTML or API JSON responses."""

import json
import re
from dataclasses import dataclass
from urllib.parse import unquote

from bs4 import BeautifulSoup


@dataclass
class VideoInfo:
    """Parsed douyin video metadata."""

    video_id: str
    desc: str
    author_nickname: str
    author_unique_id: str
    create_time: int
    duration_ms: int
    width: int
    height: int
    no_watermark_url: str
    watermark_url: str = ""
    music_url: str = ""
    cover_url: str = ""


def parse_from_render_data(html: str) -> VideoInfo | None:
    """Parse video info from embedded JSON in page HTML.

    Tries multiple strategies to find video data:
    1. <script id="RENDER_DATA"> (traditional SSR)
    2. <script id="__NEXT_DATA__"> or similar JSON islands
    3. window._ROUTER_DATA inline JavaScript assignments
    4. Any <script type="application/json"> that contains aweme_id

    Returns None if the data can't be found or parsed.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: RENDER_DATA script tag
    script_tag = soup.find("script", id="RENDER_DATA")
    if script_tag and script_tag.string:
        try:
            decoded = unquote(script_tag.string.strip())
            data = json.loads(decoded)
            detail = _extract_detail_from_render_json(data)
            if detail:
                return _extract_video_info(detail)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Strategy 2: Search all script[type="application/json"] tags
    for tag in soup.find_all("script", type="application/json"):
        if tag.string:
            try:
                data = json.loads(tag.string.strip())
                detail = _find_aweme_in_dict(data)
                if detail:
                    return _extract_video_info(detail)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    # Strategy 3: Find window._ROUTER_DATA or similar in inline scripts
    for tag in soup.find_all("script"):
        if not tag.string:
            continue
        # Look for JavaScript variable assignments containing JSON
        for pattern in [r"window\._ROUTER_DATA\s*=\s*({.+?});", r"self\.__next_f\.push\((.+?)\)"]:
            m = re.search(pattern, tag.string, re.DOTALL)
            if m:
                try:
                    # May be a list wrapped in array push
                    raw = m.group(1)
                    if raw.startswith("["):
                        data = json.loads(raw)
                        # __next_f.push often wraps JSON in an array
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, str):
                                    try:
                                        item_data = json.loads(item)
                                        detail = _find_aweme_in_dict(item_data)
                                        if detail:
                                            return _extract_video_info(detail)
                                    except json.JSONDecodeError:
                                        continue
                    else:
                        data = json.loads(raw)
                        detail = _find_aweme_in_dict(data)
                        if detail:
                            return _extract_video_info(detail)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

    # Strategy 4: Search for any JSON containing "aweme_id" in script tags
    for tag in soup.find_all("script"):
        if not tag.string or "aweme_id" not in tag.string:
            continue
        try:
            # Try to extract JSON objects from the script content
            for m in re.finditer(r'\{[^{}]*"aweme_id"\s*:\s*"[^"]+"[^{}]*\}', tag.string):
                try:
                    data = json.loads(m.group())
                    if "video" in data and "play_addr" in data.get("video", {}):
                        return _extract_video_info(data)
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    return None


def _extract_detail_from_render_json(data: dict) -> dict | None:
    """Try multiple paths to find aweme detail in RENDER_DATA JSON."""
    detail = _deep_get(data, "aweme/detail")
    if detail:
        return detail
    detail = data.get("aweme_detail")
    if detail:
        return detail
    app_data = data.get("app", {})
    detail = app_data.get("aweme", {}).get("detail")
    return detail


def _find_aweme_in_dict(data: dict) -> dict | None:
    """Recursively search a dict for video detail data containing aweme_id + video.play_addr."""
    if not isinstance(data, dict):
        return None

    # Direct match: has aweme_id and video.play_addr
    if "aweme_id" in data and "video" in data:
        video = data.get("video", {})
        if isinstance(video, dict) and "play_addr" in video:
            return data

    # Search known container keys
    for key in ("aweme_detail", "aweme/detail", "detail", "item_struct", "aweme"):
        if key in data and isinstance(data[key], dict):
            result = _find_aweme_in_dict(data[key])
            if result:
                return result

    # Search in lists
    for v in data.values():
        if isinstance(v, (dict, list)):
            if isinstance(v, dict):
                result = _find_aweme_in_dict(v)
                if result:
                    return result
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        result = _find_aweme_in_dict(item)
                        if result:
                            return result

    return None


def parse_from_aweme_detail(json_data: dict) -> VideoInfo | None:
    """Parse video info from douyin aweme/detail API response.

    The response has an ``aweme_detail`` key containing the video metadata.
    """
    detail = json_data.get("aweme_detail")
    if not detail:
        return None
    return _extract_video_info(detail)


def parse_from_item_info(json_data: dict) -> VideoInfo | None:
    """Parse video info from iesdouyin iteminfo API response.

    Fallback strategy when RENDER_DATA extraction fails.
    """
    item_list = json_data.get("item_list") or [json_data]
    if not item_list:
        return None

    detail = item_list[0]
    return _extract_video_info(detail)


def _extract_video_info(detail: dict) -> VideoInfo | None:
    """Populate VideoInfo from a raw aweme detail dict."""
    video = detail.get("video")
    if not video:
        return None

    author = detail.get("author", {})
    music = detail.get("music", {})

    # Non-watermarked play address
    play_addr = video.get("play_addr", {})
    play_url_list = play_addr.get("url_list") or []
    no_watermark_url = _pick_best_url(play_url_list)

    # Watermarked download address (fallback)
    download_addr = video.get("download_addr", {})
    dw_url_list = download_addr.get("url_list") or []
    watermark_url = _pick_best_url(dw_url_list)

    # Music / audio-only URL
    music_play = music.get("play_url", {})
    music_url_list = music_play.get("url_list") or []
    music_url = _pick_best_url(music_url_list)

    # Cover image
    cover = video.get("cover", {})
    cover_url_list = cover.get("url_list") or []
    cover_url_media = video.get("origin_cover", {}).get("url_list") or cover_url_list
    cover_url = _pick_best_url(cover_url_media)

    duration = video.get("duration", 0)
    if isinstance(duration, list):
        # Some API versions wrap duration in a list
        duration = duration[0] if duration else 0

    video_id = detail.get("aweme_id", "")
    if not video_id:
        return None

    return VideoInfo(
        video_id=str(video_id),
        desc=detail.get("desc", ""),
        author_nickname=author.get("nickname", ""),
        author_unique_id=author.get("unique_id", author.get("short_id", "")),
        create_time=detail.get("create_time", 0),
        duration_ms=int(duration),
        width=video.get("width", 0),
        height=video.get("height", 0),
        no_watermark_url=no_watermark_url,
        watermark_url=watermark_url,
        music_url=music_url,
        cover_url=cover_url,
    )


def _pick_best_url(url_list: list[str]) -> str:
    """Select the best quality URL from a list.

    Prioritizes direct mp4/m4a URLs over m3u8 playlists.
    The first non-m3u8 entry is usually the highest bitrate direct mp4.
    """
    if not url_list:
        return ""
    # Prefer non-m3u8 URLs
    for url in url_list:
        if url and "m3u8" not in url:
            return url
    # Fall back to first available URL
    return url_list[0] if url_list else ""


def _deep_get(data: dict, key_path: str) -> dict | None:
    """Traverse a nested dict using a '/' separated key path.

    e.g. _deep_get(data, "aweme/detail") -> data["aweme/detail"]
    or for nested fallback: retries with the full literal key.
    """
    # First try: exact key (handles keys with literal slashes)
    if key_path in data:
        return data[key_path]
    # Second try: segmented traversal
    keys = key_path.split("/")
    current = data
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return None
    return current if isinstance(current, dict) else None
