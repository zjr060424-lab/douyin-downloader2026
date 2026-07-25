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
from dydownload.mux import find_ffmpeg, mux_dash
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
    """Discriminated union over the three post kinds (Douyin video / image, Bilibili)."""

    video: VideoResult | None = None
    image: ImageResult | None = None
    bilibili: "BilibiliResult | None" = None

    @property
    def paths(self) -> list[Path]:
        if self.video:
            return [self.video.output_path]
        if self.image:
            return self.image.files
        if self.bilibili:
            return [p.output_path for p in self.bilibili.parts]
        return []


# ── URL parsing ────────────────────────────────────────────────────────────


_URL_PATTERNS = [
    r"https?://v\.douyin\.com/\S+",
    r"https?://www\.douyin\.com/(?:video|note)/(?:\d+)",
    r"https?://www\.iesdouyin\.com/share/(?:video|note)/(?:\d+)",
    r"https?://(?:www\.|m\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)[^\s]*",
    r"https?://b23\.tv/[^\s]+",
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


# Keep a stable reference before the compatibility wrapper below is defined.
_download_douyin_impl = download_aweme


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


# ════════════════════════════════════════════════════════════════════════════
# Bilibili (B站) dispatch
# ════════════════════════════════════════════════════════════════════════════

from dydownload.bilibili.api_client import (
    BilibiliAPIError,
    BilibiliCookieExpiredError,
    BilibiliNotFoundError,
    BangumiNotSupportedError,
    build_headers as _bili_build_headers,
    extract_av as _bili_extract_av,
    extract_bv as _bili_extract_bv,
    fetch_playurl,
    fetch_view,
    fetch_wbi_keys,
    is_bangumi_url,
    pick_streams,
    resolve_short_link as _bili_resolve_short_link,
)
from dydownload.bilibili.video_parser import MediaInfo, PageInfo


@dataclass
class BilibiliResult:
    """Outcome of a (possibly multi-part) bilibili download."""

    info: MediaInfo
    parts: list[VideoResult]   # one entry per downloaded part
    size_bytes: int


# Platform-detection markers (substring checks; cheap).
_BILI_MARKERS = ("bilibili.com", "b23.tv", "www.bilibili.com", "m.bilibili.com")
_DOUYIN_MARKERS = ("douyin.com", "iesdouyin.com", "v.douyin.com")


def detect_platform(url: str) -> str:
    """Classify ``url`` as ``"bilibili"`` or ``"douyin"``.

    Raises ``ValueError`` if neither pattern matches.
    """
    text = (url or "").lower()
    for m in _BILI_MARKERS:
        if m in text:
            return "bilibili"
    for m in _DOUYIN_MARKERS:
        if m in text:
            return "douyin"
    raise ValueError(f"无法识别链接所属平台（既不是 B 站也不是抖音）: {url}")


def download_aweme(
    url: str,
    cookie_string: str,
    output_dir: Path | None = None,
    on_event=None,
) -> DownloadResult:
    """Backwards-compatible Douyin-only download entry point."""
    return _download_douyin_impl(
        url, cookie_string, output_dir=output_dir, on_event=on_event
    )


def _safe_bvid(url: str) -> str:
    """Resolve ``url`` and return its BV id (or av string)."""
    resolved = _bili_resolve_short_link(url, cookie_string="")
    bv = _bili_extract_bv(resolved) or _bili_extract_bv(url)
    if not bv:
        av = _bili_extract_av(resolved) or _bili_extract_av(url)
        if av:
            return f"av{av}"
    return bv


def download_douyin(
    url: str,
    cookie_string: str,
    output_dir: Path | None = None,
    on_event=None,
) -> DownloadResult:
    """Alias for the original ``download_aweme`` (Douyin-only)."""
    return _download_douyin_impl(
        url, cookie_string, output_dir=output_dir, on_event=on_event
    )


def download_media(
    url: str,
    cookie_string: str,
    output_dir: Path | None = None,
    on_event=None,
    *,
    platform: str = "auto",
    qn: int = 80,
    prefer_dash: bool = True,
    multi_part_mode: str = "all",
    mux: bool = True,
) -> DownloadResult:
    """Auto-dispatching top-level entry.

    Args:
        url: Any supported Douyin or Bilibili URL.
        cookie_string: Cookie header. For bilibili must contain SESSDATA.
        output_dir: Base output directory (per-platform defaults applied).
        on_event: Optional progress callback.
        platform: ``"auto"`` (default), ``"douyin"``, or ``"bilibili"``. When
            ``"auto"`` the platform is decided by URL inspection.
        qn: Quality code (bilibili only) — 80=1080p, 120=4K, etc.
        prefer_dash: Try DASH stream first (bilibili only).
        multi_part_mode: ``"all"`` (download every P) or ``"first"`` (P1 only).
    """
    platform = (platform or "auto").lower()
    if platform == "auto":
        platform = detect_platform(url)

    if platform == "douyin":
        return download_douyin(url, cookie_string, output_dir=output_dir, on_event=on_event)
    if platform == "bilibili":
        return download_bilibili(
            url, cookie_string,
            output_dir=output_dir, on_event=on_event,
            qn=qn, prefer_dash=prefer_dash,
            multi_part_mode=multi_part_mode,
            mux=mux,
        )
    raise ValueError(f"未知平台: {platform!r}")


def download_bilibili(
    url: str,
    cookie_string: str,
    output_dir: Path | None = None,
    on_event=None,
    *,
    qn: int = 80,
    prefer_dash: bool = True,
    multi_part_mode: str = "all",
    mux: bool = True,
) -> DownloadResult:
    """Download one bilibili (B站) video or multi-part collection.

    Args:
        url: bilibili.com/video/BV... or b23.tv shortlink.
        cookie_string: Douyin-side headers are *ignored*; SESSDATA required for
            1080p+ quality.
        output_dir: Base output directory (default: ``config.DOWNLOAD_DIR``).
        on_event: Progress callback. Standard events:
              - ``"phase"``: e.g. ``"解析 B 站视频"``
              - ``"info"``: ``{platform, title, author, bvid, pages, …}``
              - ``"part"``: ``{index, total, title}`` — multi-part switch
              - ``"file"``: ``{name, index, total, status, downloaded, size, path}``
              - ``"done"``: ``DownloadResult`` (with ``bilibili`` populated)
    """
    from dydownload.config import DOWNLOAD_DIR as _DEFAULT_DIR
    if output_dir is None:
        output_dir = _DEFAULT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve short link
    if "b23.tv" in url:
        url = _bili_resolve_short_link(url, cookie_string)

    # 2. Reject bangumi (out of scope for v1)
    if is_bangumi_url(url) or "/bangumi/" in url:
        raise BangumiNotSupportedError(
            "B站番剧 / bangumi 链接暂不支持（只支持普通视频）。"
        )

    # 3. Resolve to BV id
    bv = _bili_extract_bv(url)
    if not bv:
        raise BilibiliAPIError(f"无法从链接中提取 BV id: {url}")

    _emit(on_event, "phase", "解析 B 站视频 (WBI 签名)")

    # 4. /view  → MediaInfo
    view_data = fetch_view(url, cookie_string)
    info = parse_from_bili_view(view_data)
    _emit(on_event, "info", {
        "platform": "bilibili",
        "media_id": info.media_id,
        "title": info.title,
        "author": info.author,
        "desc": info.desc[:120],
        "pages": len(info.pages),
        "width": info.width,
        "height": info.height,
        "duration": info.duration,
    })

    # 5. Choose pages
    if not info.pages:
        raise BilibiliAPIError("B 站接口未返回分 P 信息")
    pages = info.pages
    if multi_part_mode == "first":
        pages = pages[:1]
    elif multi_part_mode != "all":
        raise ValueError(
            f"multi_part_mode 只支持 'all' / 'first'，收到: {multi_part_mode!r}"
        )

    # 6. Each page → fetch /playurl → download
    parts: list[VideoResult] = []
    total_bytes = 0
    for idx, page in enumerate(pages, start=1):
        if len(pages) > 1:
            _emit(on_event, "part", {
                "index": idx,
                "total": len(pages),
                "title": page.part_title or info.title,
            })

        page_vr = _download_bilibili_page(
            info, page, idx, len(pages),
            output_dir=output_dir,
            cookie_str=cookie_string,
            qn=qn, prefer_dash=prefer_dash,
            mux=mux,
            on_event=on_event,
        )
        parts.append(page_vr)
        try:
            total_bytes += page_vr.output_path.stat().st_size
        except Exception:
            pass

        # Audio companion file (if it exists alongside) — append to size.
        aud_sibling = page_vr.output_path.with_name(
            page_vr.output_path.stem.replace("_video", "_audio") + ".m4s"
        )
        if aud_sibling.exists():
            total_bytes += aud_sibling.stat().st_size

    result = DownloadResult(
        bilibili=BilibiliResult(info=info, parts=parts, size_bytes=total_bytes)
    )
    _emit(on_event, "done", result)
    return result


def _download_bilibili_page(
    info: MediaInfo,
    page: PageInfo,
    idx: int,
    total: int,
    output_dir: Path,
    cookie_str: str,
    qn: int,
    prefer_dash: bool,
    mux: bool,
    on_event,
) -> VideoResult:
    """Download a single B 站 page."""
    _emit(on_event, "phase", f"下载分 P {idx}/{total} (cid={page.cid})")

    playurl = fetch_playurl(
        info.media_id, page.cid,
        cookie_string=cookie_str,
        qn=qn, fnval=16, fnver=0, fourk=1,
    )
    plan = pick_streams(playurl, prefer_dash=prefer_dash, qn=qn)
    if not plan:
        raise BilibiliAPIError(f"playurl 未返回可用 stream (cid={page.cid})")

    # Build filenames. Page suffix: _P1 only if multi-part.
    base = _safe_bili_base(info.title)
    suffix = f"_P{page.page:02d}" if total > 1 else ""
    headers = _bili_build_headers(
        cookie_str,
        referer=f"https://www.bilibili.com/video/{info.media_id}/?p={page.page}",
    )

    if plan["kind"] == "single":
        url = plan["url"]
        ext = _ext_from_url(url, "mp4")
        out = output_dir / f"{base}-{info.media_id}{suffix}{ext}"

        # Wrap download_progress with on_event "file"
        def _cb(downloaded, tot, status=None):
            _emit(on_event, "file", {
                "name": out.name,
                "index": idx,
                "total": total,
                "status": "done" if status == "done" else "downloading",
                "downloaded": downloaded,
                "size": tot or 0,
                "path": str(out) if status == "done" else None,
            })

        download_video(url, out, headers=headers, progress_callback=_cb)
        size = out.stat().st_size if out.exists() else 0
        # Build a stub VideoResult with the bilibili MediaInfo shimmed on .info
        shim = MediaInfoShim(info, page, plan, kind="single")
        return VideoResult(info=shim, output_path=out, size_bytes=size)

    # DASH: download video (+ audio if present) into sibling files.
    video_url = plan["video_url"]
    audio_url = plan.get("audio_url") or ""
    ext_v = _ext_from_url(video_url, "m4s")
    out_v = output_dir / f"{base}-{info.media_id}{suffix}_video{ext_v}"

    def _cb_v(downloaded, tot, status=None):
        _emit(on_event, "file", {
            "name": out_v.name,
            "index": idx,
            "total": total,
            "status": "done" if status == "done" else "downloading",
            "downloaded": downloaded,
            "size": tot or 0,
            "path": str(out_v) if status == "done" else None,
        })

    download_video(video_url, out_v, headers=headers, progress_callback=_cb_v)
    size = out_v.stat().st_size if out_v.exists() else 0

    if audio_url:
        ext_a = _ext_from_url(audio_url, "m4s")
        out_a = output_dir / f"{base}-{info.media_id}{suffix}_audio{ext_a}"

        def _cb_a(downloaded, tot, status=None):
            _emit(on_event, "file", {
                "name": out_a.name,
                "index": idx,
                "total": total,
                "status": "done" if status == "done" else "downloading",
                "downloaded": downloaded,
                "size": tot or 0,
                "path": str(out_a) if status == "done" else None,
            })

        try:
            download_video(audio_url, out_a, headers=headers,
                           progress_callback=_cb_a)
            size += out_a.stat().st_size if out_a.exists() else 0
            if mux:
                ffmpeg = find_ffmpeg()
                if ffmpeg:
                    final_out = output_dir / f"{base}-{info.media_id}{suffix}.mp4"
                    _emit(on_event, "phase", "ffmpeg 合流 DASH 音视频")
                    try:
                        mux_dash(out_v, out_a, final_out, ffmpeg=ffmpeg)
                        out_v.unlink(missing_ok=True)
                        out_a.unlink(missing_ok=True)
                        final_size = final_out.stat().st_size
                        _emit(on_event, "file", {
                            "name": final_out.name,
                            "index": idx,
                            "total": total,
                            "status": "done",
                            "downloaded": final_size,
                            "size": final_size,
                            "path": str(final_out),
                        })
                        shim = MediaInfoShim(info, page, plan, kind="dash")
                        return VideoResult(
                            info=shim,
                            output_path=final_out,
                            size_bytes=final_size,
                        )
                    except Exception as exc:
                        console.print(
                            f"[yellow]  [!] ffmpeg 合流失败，保留分轨文件: {exc}[/yellow]"
                        )
                else:
                    _emit(
                        on_event,
                        "phase",
                        "未找到 ffmpeg；保留 DASH 视频/音频分轨文件",
                    )
            else:
                _emit(on_event, "phase", "DASH 分轨下载完成（已关闭自动合流）")
        except Exception as e:
            console.print(f"[yellow]  [!] DASH 音频下载失败: {e}[/yellow]")

    shim = MediaInfoShim(info, page, plan, kind="dash")
    return VideoResult(info=shim, output_path=out_v, size_bytes=size)


class MediaInfoShim(VideoInfo):
    """Adapts a bilibili MediaInfo+Page so existing VideoResult fields
    (``.desc``, ``.author_unique_id``, ``.video_id``) read sensibly.
    """

    def __init__(self, info: MediaInfo, page: PageInfo, plan: dict, *, kind: str):
        super().__init__(
            video_id=info.media_id,
            desc=info.title,
            author_nickname=info.author,
            author_unique_id=info.author,
            create_time=0,
            duration_ms=int(info.duration) * 1000,
            width=int(plan.get("width") or info.width),
            height=int(plan.get("height") or info.height),
            no_watermark_url=(plan.get("url") or plan.get("video_url") or ""),
            music_url="",
            cover_url=info.cover_url,
        )
        self.bili_info = info
        self.bili_page = page
        self.bili_plan = plan
        self.kind = kind


def _safe_bili_base(text: str) -> str:
    """Like ``sanitize_basename`` but with a B站 default."""
    return sanitize_basename(text or "", fallback="bilibili_video", max_len=80)


def parse_from_bili_view(view_data: dict) -> MediaInfo:
    """Module-level alias to keep the pipeline self-contained."""
    from dydownload.bilibili.video_parser import parse_view as _pv
    return _pv(view_data)