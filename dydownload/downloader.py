"""Streaming video downloader with progress bar and resume support."""

import time
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


def download_video(
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
            # Get file size via HEAD first
            if total_size == 0:
                with httpx.Client(headers=headers, timeout=30.0) as head_client:
                    head_resp = head_client.head(url)
                    head_resp.raise_for_status()
                    content_length = head_resp.headers.get("Content-Length")
                    if content_length:
                        total_size = int(content_length)

            resume_headers = dict(headers)
            if downloaded_bytes > 0 and total_size > 0:
                if downloaded_bytes >= total_size:
                    # Already fully downloaded
                    part_path.rename(output_path)
                    return output_path
                resume_headers["Range"] = f"bytes={downloaded_bytes}-"

            # Prepare progress bar
            progress = Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            )

            with progress:
                task_id: TaskID = progress.add_task(
                    filename, total=total_size or 0, completed=downloaded_bytes
                )

                with httpx.Client(headers=resume_headers, timeout=120.0) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()

                        # If server ignored Range request, we get full file back
                        if response.status_code == 200 and downloaded_bytes > 0:
                            progress.reset(task_id, total=total_size or 0, completed=0)
                            downloaded_bytes = 0

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
                if actual_size < total_size:
                    raise httpx.RequestError(
                        f"下载不完整 ({actual_size}/{total_size} bytes)"
                    )

            # Rename .part to final filename
            if part_path.exists():
                if output_path.exists():
                    output_path.unlink()
                part_path.rename(output_path)

            console.print(f"[green]✓ 下载完成: {output_path}")
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
