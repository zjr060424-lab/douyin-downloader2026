"""Common utility functions."""

import re
import random
import unicodedata
from pathlib import Path

from dydownload.config import USER_AGENTS


def random_ua() -> str:
    """Return a random User-Agent from the pool."""
    return random.choice(USER_AGENTS)


def extract_video_id(text: str) -> str | None:
    """Extract douyin video ID from a URL or raw text.

    Supports these formats:
        - https://v.douyin.com/xxxxx/          (short link, needs resolution)
        - https://www.douyin.com/video/7123456789012345678
        - https://www.douyin.com/note/7123456789012345678   (image note, not video)
        - 7123456789012345678                   (raw video ID)
        - https://www.iesdouyin.com/share/video/7123456789012345678/

    Returns the numeric video_id string, or None if not found.
    """
    text = text.strip()
    # Already a raw numeric ID (e.g. 19 digits)
    if re.fullmatch(r"\d{15,20}", text):
        return text
    # Full video URL: /video/{id} or /note/{id}
    m = re.search(r"/(?:video|note|share/video)/(\d{15,20})", text)
    if m:
        return m.group(1)
    # Short link: v.douyin.com/xxxxx/ — can't extract ID directly; caller must resolve
    return None


def is_short_link(url: str) -> bool:
    """Check if the URL is a v.douyin.com short link."""
    return "v.douyin.com" in url


def sanitize_filename(text: str, video_id: str, max_len: int = 80) -> str:
    """Create a safe filename from video description and ID.

    Removes characters illegal on Windows / Unix and truncates to max_len.
    The video_id is always appended to ensure uniqueness.
    """
    # Remove or replace problematic characters
    text = text.strip() or "douyin_video"
    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)
    # Remove control chars, emojis, and common separators
    text = re.sub(r"[\r\n\t]", " ", text)
    text = re.sub(r"[\\/:*?\"<>|#\x00-\x1f]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Truncate
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    filename = f"{text}-{video_id}.mp4"
    return filename


def validate_download_dir(dir_path: Path) -> Path:
    """Ensure download directory exists, create if needed."""
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path
