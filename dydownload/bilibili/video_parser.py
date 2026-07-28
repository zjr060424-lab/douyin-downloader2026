"""Bilibili video metadata parsing.

Data classes mirror the Douyin ``VideoInfo`` shape *just enough* to be usable
by the same ``Pipeline`` flow, but kept under a generic ``MediaInfo`` name so
that the pipeline dispatcher can route them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageInfo:
    """One part ("P") of a multi-part bilibili video."""

    page: int             # 1-based part number
    cid: int
    part_title: str
    duration: int         # seconds
    width: int = 0
    height: int = 0


@dataclass
class MediaInfo:
    """High-level bilibili video metadata (parallels Douyin ``VideoInfo``)."""

    platform: str = "bilibili"
    media_id: str = ""      # BV id
    aid: int = 0            # AV id (numeric)
    title: str = ""
    desc: str = ""
    author: str = ""
    author_id: int = 0
    cover_url: str = ""
    duration: int = 0       # seconds (whole-video)
    width: int = 0
    height: int = 0
    pages: list[PageInfo] = field(default_factory=list)

    @property
    def is_multi_part(self) -> bool:
        return len(self.pages) > 1


def parse_view(view_data: dict) -> MediaInfo:
    """Convert ``/x/web-interface/view`` JSON dict → ``MediaInfo``."""
    payload = (view_data or {}).get("data") or {}
    pages_raw = payload.get("pages") or []
    pages: list[PageInfo] = []
    for p in pages_raw:
        try:
            pages.append(
                PageInfo(
                    page=int(p.get("page", 0)),
                    cid=int(p.get("cid", 0)),
                    part_title=str(p.get("part", "")),
                    duration=int(p.get("duration", 0)),
                    width=int(p.get("width", 0)),
                    height=int(p.get("height", 0)),
                )
            )
        except (TypeError, ValueError):
            continue

    owner = payload.get("owner") or {}
    return MediaInfo(
        platform="bilibili",
        media_id=str(payload.get("bvid", "")),
        aid=int(payload.get("aid", 0)),
        title=str(payload.get("title", "")),
        desc=str(payload.get("desc", "")),
        author=str(owner.get("name", "")),
        author_id=int(owner.get("mid", 0)),
        cover_url=str(payload.get("pic", "")),
        duration=int(payload.get("duration", 0)),
        width=int(payload.get("width", 0)),
        height=int(payload.get("height", 0)),
        pages=pages,
    )


@dataclass
class StreamPlan:
    """What a /playurl response tells us to actually download.

    ``kind`` is one of:
      - ``"dash"``     → separate video_url + audio_url to be muxed (or kept as .m4s).
      - ``"single"``   → already-muxed MP4/FLV in ``url``.
    """

    kind: str
    quality: int = 80
    width: int = 0
    height: int = 0
    duration: int = 0
    url: str = ""           # for "single"
    video_url: str = ""     # for "dash"
    audio_url: str = ""     # for "dash"
