"""Locate ffmpeg and mux Bilibili DASH video/audio tracks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffmpeg() -> str | None:
    """Return an ffmpeg executable path, or ``None`` when unavailable.

    Order matters: when shipped via PyInstaller (frozen), the conda env that
    built the project is still on disk, so prefer those paths — the conda-
    built ffmpeg.exe resolves its bundled DLLs relative to its real install
    path and fails STATUS_DLL_NOT_FOUND if invoked through a copy.
    """
    candidates: list[Path] = []
    # Known conda env that built the project — try first because the conda
    # ffmpeg is a hard dependency on its real install path.
    candidates.append(Path("E:/conda/envs/dydownload/Library/bin/ffmpeg.exe"))
    candidates.append(Path("C:/conda/envs/dydownload/Library/bin/ffmpeg.exe"))
    for envs_root in (
        Path("E:/conda/envs"),
        Path("C:/conda/envs"),
        Path.home() / "conda" / "envs",
        Path.home() / ".conda" / "envs",
        Path.home() / "miniconda3" / "envs",
    ):
        if envs_root.is_dir():
            for env in envs_root.iterdir():
                candidates.append(env / "Library" / "bin" / "ffmpeg.exe")
                candidates.append(env / "bin" / "ffmpeg.exe")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "ffmpeg.exe")
    candidates.extend([
        Path.home() / ".dydownload" / "ffmpeg.exe",
        Path.home() / ".dydownload" / "ffmpeg",
    ])
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix and sys.prefix:
        prefix = sys.prefix
    if prefix:
        candidates.append(Path(prefix) / "Library" / "bin" / "ffmpeg.exe")
        candidates.append(Path(prefix) / "bin" / "ffmpeg.exe")
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
    # conda-built ffmpeg resolves its DLLs relative to its own cwd, so make
    # sure the ffmpeg directory is on PATH for the subprocess. Otherwise the
    # PyInstaller-frozen GUI (cwd = sys._MEIPASS) loses DLL search context.
    ffmpeg_dir = str(Path(executable).resolve().parent)
    sub_env = os.environ.copy()
    sub_env["PATH"] = ffmpeg_dir + os.pathsep + sub_env.get("PATH", "")
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
        env=sub_env,
        cwd=ffmpeg_dir,
    )
    if completed.returncode != 0 or not output_path.exists():
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"ffmpeg 合流失败: {detail}")
    return output_path
