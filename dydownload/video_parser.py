"""Extract video info from Douyin page HTML or API JSON responses."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from bs4 import BeautifulSoup


@dataclass
class VideoInfo:
    """Parsed douyin aweme metadata (video OR image post)."""

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
    # ── media type: "video" (default) or "image" (图文/图集) ──
    media_type: str = "video"
    # For image posts: parallel lists, one entry per image.
    # ``images`` holds the still-image URLs (jpeg preferred).
    # ``image_live_urls`` holds the live-photo mp4 URL for that image, or "" if none.
    images: list[str] = field(default_factory=list)
    image_live_urls: list[str] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        return self.media_type == "image"


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

    # Direct match: image post (图文/图集) — has aweme_id and a non-empty images list
    if "aweme_id" in data and isinstance(data.get("images"), list) and data["images"]:
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
    """Populate VideoInfo from a raw aweme detail dict.

    Handles both regular videos and image posts (图文/图集). Image posts are
    detected by a non-empty ``images`` list or ``aweme_type == 68``; they carry
    their media in ``images[]`` rather than ``video.play_addr``.
    """
    video_id = detail.get("aweme_id", "")
    if not video_id:
        return None

    author = detail.get("author", {}) or {}
    music = detail.get("music", {}) or {}

    # Music / audio-only URL (background music, present for both types)
    music_play = music.get("play_url", {}) or {}
    music_url_list = music_play.get("url_list") or []
    music_url = _pick_best_url(music_url_list)

    images = detail.get("images")
    is_image_post = detail.get("aweme_type") == 68 or (
        isinstance(images, list) and len(images) > 0
    )

    if is_image_post and isinstance(images, list) and images:
        return _extract_image_info(
            detail, images, video_id, author, music_url
        )

    # ── Regular video ──
    video = detail.get("video")
    if not video:
        return None

    # Non-watermarked play address
    play_addr = video.get("play_addr", {})
    play_url_list = play_addr.get("url_list") or []
    no_watermark_url = _pick_best_url(play_url_list)

    # Watermarked download address (fallback)
    download_addr = video.get("download_addr", {})
    dw_url_list = download_addr.get("url_list") or []
    watermark_url = _pick_best_url(dw_url_list)

    # Cover image
    cover = video.get("cover", {})
    cover_url_list = cover.get("url_list") or []
    cover_url_media = video.get("origin_cover", {}).get("url_list") or cover_url_list
    cover_url = _pick_best_url(cover_url_media)

    duration = video.get("duration", 0)
    if isinstance(duration, list):
        # Some API versions wrap duration in a list
        duration = duration[0] if duration else 0

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
        media_type="video",
    )


def _extract_image_info(
    detail: dict,
    images: list,
    video_id: str,
    author: dict,
    music_url: str,
) -> VideoInfo | None:
    """Populate a VideoInfo for an image post (图文/图集)."""
    image_urls: list[str] = []
    live_urls: list[str] = []
    width = height = 0

    for img in images:
        if not isinstance(img, dict):
            continue
        url = _pick_image_url(img.get("url_list") or [])
        if not url:
            # Fall back to watermarked download list if url_list is empty
            url = _pick_image_url(img.get("download_url_list") or [])
        if not url:
            continue
        image_urls.append(url)

        # Live photo: an mp4 attached to this image
        live = ""
        img_video = img.get("video")
        if isinstance(img_video, dict):
            live_play = img_video.get("play_addr", {}) or {}
            live = _pick_best_url(live_play.get("url_list") or [])
        live_urls.append(live)

        if width == 0:
            width = img.get("width", 0) or 0
            height = img.get("height", 0) or 0

    if not image_urls:
        return None

    # Cover: first image, or the aweme-level cover if present
    cover_url = image_urls[0]

    return VideoInfo(
        video_id=str(video_id),
        desc=detail.get("desc", ""),
        author_nickname=author.get("nickname", ""),
        author_unique_id=author.get("unique_id", author.get("short_id", "")),
        create_time=detail.get("create_time", 0),
        duration_ms=0,
        width=width,
        height=height,
        no_watermark_url="",
        watermark_url="",
        music_url=music_url,
        cover_url=cover_url,
        media_type="image",
        images=image_urls,
        image_live_urls=live_urls,
    )


def _pick_image_url(url_list: list[str]) -> str:
    """Select the best image URL from a list, preferring jpeg over webp/heic.

    Douyin returns several CDN mirrors of the same image in different formats.
    jpeg has the widest tool/OS compatibility, so prefer it; then avoid
    heic/heif; otherwise fall back to the first entry.
    """
    if not url_list:
        return ""
    # Prefer an explicit jpeg/jpg URL
    for url in url_list:
        if url and re.search(r"\.jpe?g(\b|[?&_])", url, re.IGNORECASE):
            return url
    # Avoid heic/heif if a non-heic option exists
    for url in url_list:
        if url and not re.search(r"\.hei[cf](\b|[?&_])", url, re.IGNORECASE):
            return url
    return url_list[0] if url_list else ""


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
