"""Streaming video downloader with progress bar and resume support."""

import time
import threading
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()
_OUTPUT_LOCKS = tuple(threading.Lock() for _ in range(64))


def _output_lock(path: Path) -> threading.Lock:
    """Return a stable striped lock for a normalized output path."""
    normalized = str(path.resolve()).casefold()
    return _OUTPUT_LOCKS[hash(normalized) % len(_OUTPUT_LOCKS)]


def _download_video_unlocked(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    chunk_size: int = 1024 * 1024,
    max_retries: int = 3,
    progress_callback: callable = None,
) -> Path:
    """Download a video with streaming, progress display, and resume support.

    Args:
        url: The direct video URL to download.
        output_path: Full path to save the file (should end with .mp4).
        headers: HTTP headers to include (must include cookie/UA).
        chunk_size: Download chunk size in bytes (default 1 MB).
        max_retries: Max retry attempts on connection failure.

    Returns:
        The path to the downloaded file.

    Raises:
        httpx.HTTPError: On unrecoverable HTTP errors.
    """
    headers = headers or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Check for partial download for resume
    part_path = output_path.with_suffix(output_path.suffix + ".part")
    downloaded_bytes = 0
    if part_path.exists():
        downloaded_bytes = part_path.stat().st_size
    else:
        # Start fresh
        part_path.touch()

    total_size = 0
    filename = output_path.name

    for attempt in range(max_retries):
        try:
            # HEAD is an optimization only. Some CDNs reject or redirect it
            # while allowing GET, so a failed probe must not abort a download.
            if total_size == 0:
                try:
                    with httpx.Client(
                        headers=headers, timeout=30.0, follow_redirects=True,
                    ) as head_client:
                        head_resp = head_client.head(url)
                        head_resp.raise_for_status()
                        content_length = head_resp.headers.get("Content-Length")
                        if content_length:
                            total_size = int(content_length)
                except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
                    total_size = 0

            resume_headers = dict(headers)
            if downloaded_bytes > 0:
                if total_size > 0 and downloaded_bytes >= total_size:
                    # Without persisted ETag/URL metadata an equal-size part
                    # may belong to an older stream. Restart instead of
                    # silently promoting stale or oversized content.
                    downloaded_bytes = 0
                resume_headers["Range"] = f"bytes={downloaded_bytes}-"
                if downloaded_bytes == 0:
                    resume_headers.pop("Range", None)

            # Prepare progress bar
            progress = Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "|",
                DownloadColumn(),
                "|",
                TransferSpeedColumn(),
                "|",
                TimeRemainingColumn(),
                console=console,
            )

            with progress:
                task_id: TaskID = progress.add_task(
                    filename, total=total_size or 0, completed=downloaded_bytes
                )

                with httpx.Client(headers=resume_headers, timeout=120.0) as client:
                    with client.stream("GET", url) as response:
                        if response.status_code == 416 and downloaded_bytes > 0:
                            downloaded_bytes = 0
                            part_path.write_bytes(b"")
                            raise httpx.RequestError(
                                "服务端拒绝断点范围，已清空临时文件并重试"
                            )
                        response.raise_for_status()

                        # If server ignored Range request, we get full file back
                        if response.status_code == 200 and downloaded_bytes > 0:
                            progress.reset(task_id, total=total_size or 0, completed=0)
                            downloaded_bytes = 0
                        elif response.status_code == 206 and downloaded_bytes > 0:
                            content_range = response.headers.get("Content-Range", "")
                            expected = f"bytes {downloaded_bytes}-"
                            if not content_range.lower().startswith(expected.lower()):
                                raise httpx.RequestError(
                                    f"断点响应范围不匹配: {content_range or 'missing'}"
                                )
                            try:
                                total_from_range = int(content_range.rsplit("/", 1)[-1])
                            except (ValueError, IndexError):
                                total_from_range = 0
                            if total_from_range > 0:
                                total_size = total_from_range

                        if total_size == 0 and response.status_code == 200:
                            try:
                                total_size = int(response.headers.get("Content-Length", 0))
                            except ValueError:
                                total_size = 0

                        mode = "ab" if downloaded_bytes > 0 else "wb"
                        with open(part_path, mode) as f:
                            for chunk in response.iter_bytes(chunk_size=chunk_size):
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                progress.update(task_id, completed=downloaded_bytes)
                                if progress_callback:
                                    progress_callback(downloaded_bytes, total_size)

            # Verify file size
            if total_size > 0:
                actual_size = part_path.stat().st_size
                if actual_size != total_size:
                    raise httpx.RequestError(
                        f"下载长度不匹配 ({actual_size}/{total_size} bytes)"
                    )

            # Rename .part to final filename
            if part_path.exists():
                if output_path.exists():
                    output_path.unlink()
                part_path.rename(output_path)

            console.print(f"[green]+ 下载完成: {output_path}")
            if progress_callback:
                progress_callback(downloaded_bytes, total_size or downloaded_bytes, "done")
            return output_path

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                console.print(
                    f"[yellow]下载失败 (尝试 {attempt + 1}/{max_retries}), "
                    f"{wait}s 后重试... [{e}]"
                )
                time.sleep(wait)
            else:
                raise


def download_video(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    chunk_size: int = 1024 * 1024,
    max_retries: int = 3,
    progress_callback: callable = None,
) -> Path:
    """Serialize writes targeting the same path within this process."""
    with _output_lock(output_path):
        return _download_video_unlocked(
            url,
            output_path,
            headers=headers,
            chunk_size=chunk_size,
            max_retries=max_retries,
            progress_callback=progress_callback,
        )


def _download_image_unlocked(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    quiet: bool = False,
) -> Path:
    """Download a single image (or small file) with retries.

    Images are small, so we skip the HEAD/Range/resume machinery used for
    videos and just stream the body to disk in one shot.

    Args:
        url: Direct image URL.
        output_path: Full path to save the file.
        headers: HTTP headers (cookie/UA/referer).
        max_retries: Max retry attempts on connection failure.
        quiet: Suppress the per-file success line.

    Returns:
        The path to the downloaded file.
    """
    headers = headers or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
            if not quiet:
                console.print(f"[green]  + {output_path.name}")
            return output_path
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 1.5)
            else:
                raise
    if last_error:
        raise last_error
    return output_path


def download_image(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    quiet: bool = False,
) -> Path:
    """Serialize small-file writes targeting the same path."""
    with _output_lock(output_path):
        return _download_image_unlocked(
            url,
            output_path,
            headers=headers,
            max_retries=max_retries,
            quiet=quiet,
        )


def get_file_size(url: str, headers: dict[str, str] | None = None) -> int:
    """Get remote file size via HEAD request."""
    headers = headers or {}
    try:
        with httpx.Client(headers=headers, timeout=15.0) as client:
            response = client.head(url)
            response.raise_for_status()
            return int(response.headers.get("Content-Length", 0))
    except Exception:
        return 0
