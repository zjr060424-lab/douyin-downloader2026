"""Smoke tests for the Bilibili (B站) integration in dydownload.

These are pure-Python asserts with no network — verify URL parsing, WBI
signing, /view parsing, /playurl stream selection, and the pipeline
dispatcher. Mirrors the style of ``smoke_tuwen.py``.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dydownload.pipeline as p
import dydownload.cli as cli
import dydownload.server as srv
import dydownload.cookie_manager as cm
import dydownload.bilibili.api_client as api
import dydownload.bilibili.video_parser as vp
from dydownload.bilibili.signature import _wbi_mixin_key, wbi_sign
from dydownload.bilibili.api_client import (
    is_bangumi_url,
    extract_av,
    extract_bv,
    pick_streams,
    probe_cookie,
)
from dydownload.bilibili.video_parser import (
    MediaInfo,
    PageInfo,
    parse_view,
)


# ── URL helpers ──────────────────────────────────────────────────────────


def test_url_helpers():
    assert extract_bv("https://www.bilibili.com/video/BV1xx411c7mD?p=1") == "BV1xx411c7mD"
    assert extract_bv("https://www.bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"
    assert extract_bv("https://example.com/no-bv") == ""

    assert extract_av("https://www.bilibili.com/video/av170001") == "170001"
    assert extract_av("https://www.bilibili.com/video/av170001/?p=2") == "170001"
    assert extract_av("https://www.bilibili.com/video/BV1xx411c7mD") == ""

    assert is_bangumi_url("https://www.bilibili.com/bangumi/play/ep12345")
    assert is_bangumi_url("https://www.bilibili.com/bangumi/play/ss12345")
    assert is_bangumi_url("https://bangumi.bilibili.com/ss12345")
    assert not is_bangumi_url("https://www.bilibili.com/video/BV1xx411c7mD")


# ── WBI signing ─────────────────────────────────────────────────────────


def test_wbi_sign_known_vector():
    assert _wbi_mixin_key(
        "7cd084941338484aae1ad9415bf840dd",
        "4932caff0ff746eab6f01bf08b70ac45",
    ) == "ea1db114af3d7062874693fa044f4ff8"
    params = {"bvid": "BV1xx411c7mD", "cid": 12345}
    signed = wbi_sign(
        params,
        "7cd084941338484aae1ad9415bf840dd",
        "4932caff0ff746eab6f01bf08b70ac45",
    )
    assert "wts" in signed and "w_rid" in signed
    assert len(signed["w_rid"]) == 32
    assert len(str(signed["wts"])) == 10
    assert signed["bvid"] == "BV1xx411c7mD" and signed["cid"] == 12345


# ── view parsing ────────────────────────────────────────────────────────


def test_parse_view_multi_page():
    payload = {
        "data": {
            "bvid": "BV1multi",
            "aid": 1,
            "title": "多 P 测试",
            "desc": "一个分 P 视频",
            "owner": {"name": "up主", "mid": 12345},
            "pic": "http://i/cover.jpg",
            "duration": 240,
            "width": 1920,
            "height": 1080,
            "pages": [
                {"page": 1, "cid": 1001, "part": "Part1", "duration": 120, "width": 1920, "height": 1080},
                {"page": 2, "cid": 1002, "part": "Part2", "duration": 120, "width": 1920, "height": 1080},
            ],
        }
    }
    info = parse_view(payload)
    assert info.platform == "bilibili"
    assert info.media_id == "BV1multi"
    assert info.title == "多 P 测试"
    assert info.author == "up主"
    assert info.author_id == 12345
    assert info.is_multi_part
    assert len(info.pages) == 2
    assert info.pages[0].cid == 1001
    assert info.pages[1].part_title == "Part2"


# ── pick_streams ────────────────────────────────────────────────────────


def test_pick_streams_dash_and_single():
    dash = pick_streams({
        "data": {
            "dash": {
                "video": [{"id": 80, "baseUrl": "http://v/v.m4s"}],
                "audio": [{"id": 30216, "baseUrl": "http://a/a.m4s"}],
            },
            "quality": 80,
            "width": 1920,
            "height": 1080,
            "timelength": 60000,
            "durl": [],
        }
    }, prefer_dash=True)
    assert dash["kind"] == "dash"
    assert dash["video_url"] == "http://v/v.m4s"
    assert dash["audio_url"] == "http://a/a.m4s"
    assert dash["quality"] == 80

    single = pick_streams({
        "data": {
            "dash": {},
            "durl": [{"url": "http://x/full.mp4", "size": 1}],
            "quality": 64,
            "width": 1280,
            "height": 720,
            "timelength": 30000,
        }
    })
    assert single["kind"] == "single"
    assert single["url"] == "http://x/full.mp4"

    empty = pick_streams({"data": {}})
    assert empty is None


# ── probe_cookie (logic only — no real /nav) ───────────────────────────


def test_probe_cookie_requires_sessdata():
    assert probe_cookie("") is False
    with patch(
        "dydownload.bilibili.api_client._fetch_nav",
        return_value={"data": {"isLogin": True}},
    ):
        assert probe_cookie("foo=bar; SESSDATA=present") is True


# ── extract_url covers both platforms ─────────────────────────────────


def test_extract_url_supports_bilibili():
    assert p.extract_url("分享 https://www.bilibili.com/video/BV1abc1234567 / 复制").endswith("BV1abc1234567")
    assert p.extract_url("5.66 https://b23.tv/abc分享").startswith("https://b23.tv/abc")


# ── detect_platform dispatcher ───────────────────────────────────────


def test_detect_platform():
    assert p.detect_platform("https://v.douyin.com/abc") == "douyin"
    assert p.detect_platform("https://www.douyin.com/note/123") == "douyin"
    assert p.detect_platform("https://www.bilibili.com/video/BV1") == "bilibili"
    assert p.detect_platform("https://b23.tv/abc") == "bilibili"
    raised = False
    try:
        p.detect_platform("https://example.com/abc")
    except ValueError:
        raised = True
    assert raised


# ── bangumi rejection at pipeline ─────────────────────────────────────


def test_pipeline_bangumi_guard():
    try:
        p.download_bilibili(
            "https://www.bilibili.com/bangumi/play/ep12345",
            cookie_string="SESSDATA=abc",
        )
    except api.BangumiNotSupportedError:
        return
    assert False, "bangumi URL should raise BangumiNotSupportedError"


# ── CLI surface ───────────────────────────────────────────────────────


def test_cli_commands():
    cmd_names = {c.callback.__name__ for c in cli.app.registered_commands}
    assert {"download", "test", "status", "serve"} <= cmd_names


def test_cli_options():
    param_names = set()
    for cmd in cli.app.registered_commands:
        callback = cmd.callback
        if callback is None:
            continue
        import inspect
        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            continue
        param_names.update(sig.parameters.keys())
    for required in {"platform", "quality", "prefer_dash", "parts", "mux"}:
        assert required in param_names, f"missing CLI option: {required}"


# ── Server surface ────────────────────────────────────────────────────


def test_server_platforms():
    handler = srv.CookieReceiverHandler
    assert hasattr(handler, "_handle_cookie")
    assert hasattr(handler, "_handle_download")


# ── Cookie manager split ─────────────────────────────────────────────


def test_cookie_manager_split():
    info = cm.load_bilibili_cookies()
    assert info.status in (
        cm.CookieStatus.MISSING,
        cm.CookieStatus.UNKNOWN,
        cm.CookieStatus.EXPIRED,
    )
    from dydownload.config import BILI_COOKIE_FILE
    assert BILI_COOKIE_FILE.name == "cookies.bilibili.txt"


# ── Driver ────────────────────────────────────────────────────────────


def main():
    tests = [
        test_url_helpers,
        test_wbi_sign_known_vector,
        test_parse_view_multi_page,
        test_pick_streams_dash_and_single,
        test_probe_cookie_requires_sessdata,
        test_extract_url_supports_bilibili,
        test_detect_platform,
        test_pipeline_bangumi_guard,
        test_cli_commands,
        test_cli_options,
        test_server_platforms,
        test_cookie_manager_split,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as e:
            failures.append((t.__name__, e))
            continue
        print(f"  + {t.__name__}")
    if failures:
        for name, e in failures:
            print(f"  X {name}: {type(e).__name__}: {e}")
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
