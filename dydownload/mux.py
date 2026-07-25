"""Locate ffmpeg and mux Bilibili DASH video/audio tracks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffmpeg() -> str | None:
    """Return an ffmpeg executable path, or ``None`` when unavailable."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "ffmpeg.exe")
    candidates.extend([
        Path.home() / ".dydownload" / "ffmpeg.exe",
        Path.home() / ".dydownload" / "ffmpeg",
    ])
    # Active conda env (set by `conda activate`, but not by bare `python`).
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix and sys.prefix:
        prefix = sys.prefix
    if prefix:
        candidates.append(Path(prefix) / "Library" / "bin" / "ffmpeg.exe")
        candidates.append(Path(prefix) / "bin" / "ffmpeg.exe")
    # Other common install roots.
    candidates.extend([
        Path("C:/conda/Library/bin/ffmpeg.exe"),
        Path("C:/ProgramData/anaconda3/Library/bin/ffmpeg.exe"),
    ])
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def mux_dash(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    ffmpeg: str | None = None,
) -> Path:
    """Mux DASH video and audio without re-encoding."""
    executable = ffmpeg or find_ffmpeg()
    if not executable:
        raise FileNotFoundError(
            "未找到 ffmpeg；请安装到 PATH 或放到 ~/.dydownload/ffmpeg.exe"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            executable,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            "-shortest",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not output_path.exists():
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"ffmpeg 合流失败: {detail}")
    return output_path
