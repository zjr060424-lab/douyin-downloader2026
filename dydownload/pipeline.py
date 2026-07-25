"""Shared download pipeline used by CLI, GUI and the local server.

Consolidates the resolve → fetch → sign → parse → download chain into one
function so video and image posts share a single code path. Image posts
(图文/图集) are downloaded into a per-post subfolder as jpeg + optional
live-photo mp4 + optional BGM.
"""

import random
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console

from dydownload.api_client import (
    CookieExpiredError,
    DouyinAPIError,
    VideoNotFoundError,
    fetch_aweme_detail,
    fetch_video_page,
)
from dydownload.config import DOWNLOAD_DIR, USER_AGENTS
from dydownload.downloader import download_image, download_video
from dydownload.signature import extract_webid
from dydownload.video_parser import VideoInfo, parse_from_aweme_detail

console = Console()


# ── Result types ────────────────────────────────────────────────────────────


@dataclass
class VideoResult:
    """Outcome of a video download."""

    info: VideoInfo
    output_path: Path
    size_bytes: int


@dataclass
class ImageResult:
    """Outcome of an image-post download."""

    info: VideoInfo
    folder: Path
    files: list[Path]  # every file written (jpegs, live videos, BGM)
    size_bytes: int


@dataclass
class DownloadResult:
    """Discriminated union over the two post kinds."""

    video: VideoResult | None = None
    image: ImageResult | None = None

    @property
    def paths(self) -> list[Path]:
        if self.video:
            return [self.video.output_path]
        if self.image:
            return self.image.files
        return []


# ── URL parsing ────────────────────────────────────────────────────────────


_URL_PATTERNS = [
    r"https?://v\.douyin\.com/\S+",
    r"https?://www\.douyin\.com/(?:video|note)/(\d+)",
    r"https?://www\.iesdouyin\.com/share/video/(\d+)",
]


def extract_url(text: str) -> str:
    """Extract the first douyin URL from a string.

    Handles raw URLs, share text blobs (e.g. ``5.66 PXM:/ … https://v.douyin.com/…``)
    and the ``/note/{id}`` shape used by image posts.
    """
    for p in _URL_PATTERNS:
        m = re.search(p, text)
        if m:
            url = m.group(0)
            # Drop a trailing slash so short links don't break path joins
            return url.rstrip("//")
    return text


def resolve_short_link(url: str) -> str:
    """Follow a v.douyin.com short link to its canonical ``/video/{id}`` page."""
    if "v.douyin.com" not in url:
        return url
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        resp = client.get(url)
        if resp.status_code in (301, 302):
            location = resp.headers.get("Location", url)
            if location:
                return location
    return url


def extract_aweme_id(url: str) -> str:
    """Extract the numeric aweme_id from any supported URL form."""
    # /video/{id} or /note/{id}
    m = re.search(r"/(?:video|note)/(\d{15,25})", url)
    if m:
        return m.group(1)
    # share/iesdouyin /share/video/{id}/
    m = re.search(r"/share/video/(\d{15,25})", url)
    if m:
        return m.group(1)
    # Bare numeric ID
    m = re.search(r"(\d{15,25})", url)
    if m:
        return m.group(1)
    return ""


# ── Sanitisation ────────────────────────────────────────────────────────────


def sanitize_basename(text: str, fallback: str = "douyin", max_len: int = 80) -> str:
    """Build a filename-safe base from a description (no extension)."""
    text = (text or "").strip() or fallback
    text = re.sub(r"[\r\n\t]", " ", text)
    text = re.sub(r"[\\/:*?\"<>|#\x00-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text or fallback


def _ext_from_url(url: str, default: str) -> str:
    """Pick an extension based on the URL's path."""
    m = re.search(r"\.([a-zA-Z0-9]{2,5})(?:[?#]|$)", url)
    if m:
        ext = m.group(1).lower()
        if ext in ("jpg", "jpeg", "png", "webp", "gif", "heic", "heif"):
            return "jpg" if ext == "jpeg" else ext
        if ext in ("mp4", "m4a", "mp3"):
            return ext
    return default


# ── Shared resolve-and-fetch ───────────────────────────────────────────────


def resolve_aweme(
    url: str,
    cookie_string: str,
    user_agent: str | None = None,
) -> tuple[str, VideoInfo]:
    """Run the full resolve → parse chain and return ``(aweme_id, info)``.

    Raises the same exceptions as ``fetch_video_page`` / ``fetch_aweme_detail``.
    """
    url = extract_url(url)
    url = resolve_short_link(url)

    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        raise DouyinAPIError(f"无法从链接中提取作品 ID: {url}")

    ua = user_agent or random.choice(USER_AGENTS)

    html = fetch_video_page(aweme_id, cookie_string)
    webid = extract_webid(html)
    if not webid:
        m2 = re.search(r'"user_unique_id"\s*:\s*"(\d+)"', html)
        if m2:
            webid = m2.group(1)

    data = fetch_aweme_detail(
        aweme_id,
        cookie_string=cookie_string,
        webid=webid or "",
        user_agent=ua,
    )
    info = parse_from_aweme_detail(data)
    if not info:
        raise DouyinAPIError(f"无法解析作品数据 (aweme_id={aweme_id})")
    return aweme_id, info


# ── Downloaders ─────────────────────────────────────────────────────────────


def download_aweme(
    url: str,
    cookie_string: str,
    output_dir: Path | None = None,
    on_event=None,
) -> DownloadResult:
    """Top-level entry point: detect the post kind and dispatch accordingly.

    Args:
        url: Any supported douyin URL.
        cookie_string: Cookie header value from the extension.
        output_dir: Base download directory; defaults to ``config.DOWNLOAD_DIR``.
        on_event: Optional callback ``(event_name, payload)`` for progress
            reporting. Used by the GUI. Events:
              - ``"phase"``  payload=str  ("解析", "下载视频", "下载图集", …)
              - ``"info"``   payload=dict with aweme metadata
              - ``"file"``   payload=dict {name, index, total, status, path?}
              - ``"done"``   payload=DownloadResult
    """
    output_dir = output_dir or DOWNLOAD_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    _emit(on_event, "phase", "解析作品链接")
    aweme_id, info = resolve_aweme(url, cookie_string)
    _emit(on_event, "info", _info_payload(info))

    if info.is_image:
        result = _download_image_post(info, output_dir, on_event)
    else:
        result = _download_video_post(info, aweme_id, output_dir, on_event)

    _emit(on_event, "done", result)
    return result


# ── Video path ──────────────────────────────────────────────────────────────


def _download_video_post(
    info: VideoInfo,
    aweme_id: str,
    output_dir: Path,
    on_event,
) -> DownloadResult:
    media_url = info.no_watermark_url
    if not media_url:
        raise DouyinAPIError("没有可用的无水印视频地址")

    base = sanitize_basename(info.desc, fallback="douyin_video")
    output_path = output_dir / f"{base}-{aweme_id}.mp4"

    _emit(on_event, "phase", f"下载视频 ({info.width}x{info.height})")

    headers = {
        "Referer": f"https://www.douyin.com/video/{aweme_id}/",
        "User-Agent": random.choice(USER_AGENTS),
    }

    def _cb(downloaded, total, status=None):
        _emit(on_event, "file", {
            "name": output_path.name,
            "index": 1,
            "total": 1,
            "status": "done" if status == "done" else "downloading",
            "downloaded": downloaded,
            "size": total,
            "path": str(output_path) if status == "done" else None,
        })

    download_video(media_url, output_path, headers=headers, progress_callback=_cb)

    size = output_path.stat().st_size
    return DownloadResult(video=VideoResult(info=info, output_path=output_path, size_bytes=size))


# ── Image path ──────────────────────────────────────────────────────────────


def _download_image_post(
    info: VideoInfo,
    output_dir: Path,
    on_event,
) -> DownloadResult:
    base = sanitize_basename(info.desc, fallback="douyin_image")
    folder = output_dir / f"{base}-{info.video_id}"
    folder.mkdir(parents=True, exist_ok=True)

    _emit(on_event, "phase", f"下载图集 ({len(info.images)} 张)")

    headers = {
        "Referer": f"https://www.douyin.com/note/{info.video_id}/",
        "User-Agent": random.choice(USER_AGENTS),
    }

    live_count = sum(1 for u in info.image_live_urls if u)
    total = len(info.images) + live_count + (1 if info.music_url else 0)
    files: list[Path] = []
    bytes_written = 0

    for idx, url in enumerate(info.images, start=1):
        ext = _ext_from_url(url, default="jpg")
        name = f"{idx:02d}.{ext}"
        target = folder / name
        _emit(on_event, "file", {
            "name": name,
            "index": idx,
            "total": total,
            "status": "downloading",
            "downloaded": 0,
            "size": 0,
            "path": None,
        })
        try:
            download_image(url, target, headers=headers, quiet=True)
        except Exception as e:
            console.print(f"[yellow]  [!] 图片 {idx} 下载失败: {e}[/yellow]")
            _emit(on_event, "file", {
                "name": name,
                "index": idx,
                "total": total,
                "status": "error",
                "downloaded": 0,
                "size": 0,
                "path": None,
            })
            continue
        size = target.stat().st_size
        bytes_written += size
        files.append(target)
        _emit(on_event, "file", {
            "name": name,
            "index": idx,
            "total": total,
            "status": "done",
            "downloaded": size,
            "size": size,
            "path": str(target),
        })

        # Live photo (实况图)
        live_url = info.image_live_urls[idx - 1] if idx - 1 < len(info.image_live_urls) else ""
        if live_url:
            live_name = f"{idx:02d}_live.mp4"
            live_target = folder / live_name
            _emit(on_event, "file", {
                "name": live_name,
                "index": len(files) + 1,
                "total": total,
                "status": "downloading",
                "downloaded": 0,
                "size": 0,
                "path": None,
            })
            try:
                download_image(live_url, live_target, headers=headers, quiet=True)
                files.append(live_target)
                bytes_written += live_target.stat().st_size
                _emit(on_event, "file", {
                    "name": live_name,
                    "index": len(files),
                    "total": total,
                    "status": "done",
                    "downloaded": live_target.stat().st_size,
                    "size": live_target.stat().st_size,
                    "path": str(live_target),
                })
            except Exception as e:
                console.print(f"[yellow]  [!] 实况视频 {idx} 下载失败: {e}[/yellow]")
                _emit(on_event, "file", {
                    "name": live_name,
                    "index": len(files) + 1,
                    "total": total,
                    "status": "error",
                    "downloaded": 0,
                    "size": 0,
                    "path": None,
                })

    # Background music
    if info.music_url:
        idx = len(files) + 1
        ext = _ext_from_url(info.music_url, default="mp3")
        bgm_name = f"bgm.{ext}"
        bgm_target = folder / bgm_name
        _emit(on_event, "file", {
            "name": bgm_name,
            "index": idx,
            "total": total,
            "status": "downloading",
            "downloaded": 0,
            "size": 0,
            "path": None,
        })
        try:
            download_image(info.music_url, bgm_target, headers=headers, quiet=True)
            files.append(bgm_target)
            bytes_written += bgm_target.stat().st_size
            _emit(on_event, "file", {
                "name": bgm_name,
                "index": idx,
                "total": total,
                "status": "done",
                "downloaded": bgm_target.stat().st_size,
                "size": bgm_target.stat().st_size,
                "path": str(bgm_target),
            })
        except Exception as e:
            console.print(f"[yellow]  [!] 背景音乐下载失败: {e}[/yellow]")
            _emit(on_event, "file", {
                "name": bgm_name,
                "index": idx,
                "total": total,
                "status": "error",
                "downloaded": 0,
                "size": 0,
                "path": None,
            })

    return DownloadResult(image=ImageResult(info=info, folder=folder, files=files, size_bytes=bytes_written))


# ── Helpers ─────────────────────────────────────────────────────────────────


def _emit(on_event, name: str, payload) -> None:
    if on_event:
        try:
            on_event(name, payload)
        except Exception as e:  # callbacks must never break the pipeline
            console.print(f"[yellow]  [!] on_event 回调异常: {e}[/yellow]")


def _info_payload(info: VideoInfo) -> dict:
    return {
        "aweme_id": info.video_id,
        "desc": info.desc,
        "author": info.author_unique_id,
        "nickname": info.author_nickname,
        "media_type": info.media_type,
        "image_count": len(info.images) if info.is_image else 0,
        "has_bgm": bool(info.music_url),
        "width": info.width,
        "height": info.height,
    }