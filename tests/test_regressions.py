"""Regression coverage for cross-module download and service contracts."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dydownload.bilibili.api_client import BilibiliAPIError
from dydownload.bilibili.signature import _wbi_mixin_key
from dydownload.bilibili.video_parser import MediaInfo, PageInfo
from dydownload.cookie_manager import CookieStatus, probe_cookie_freshness
from dydownload.pipeline import (
    BilibiliResult,
    DownloadResult,
    VideoResult,
    _download_bilibili_page,
    download_bilibili,
    download_media,
)
from dydownload.server import _origin_is_allowed
from dydownload.gui import App


class ServiceSecurityTests(unittest.TestCase):
    def test_only_extension_browser_origins_are_allowed(self):
        self.assertTrue(_origin_is_allowed(None))
        self.assertTrue(_origin_is_allowed("chrome-extension://example"))
        self.assertTrue(_origin_is_allowed("moz-extension://example"))
        self.assertFalse(_origin_is_allowed("https://example.com"))
        self.assertFalse(_origin_is_allowed("http://localhost:3000"))

    def test_gui_log_sanitizer_preserves_chinese(self):
        self.assertEqual(App._safe_log("下载失败：网络异常"), "下载失败：网络异常")


class BilibiliRegressionTests(unittest.TestCase):
    def setUp(self):
        self.page = PageInfo(page=1, cid=42, part_title="P1", duration=1)
        self.info = MediaInfo(
            media_id="BV1xx411c7mD",
            aid=170001,
            title="Example",
            author="Tester",
            pages=[self.page],
        )

    def test_standard_wbi_mixin_vector(self):
        actual = _wbi_mixin_key(
            "7cd084941338484aae1ad9415bf840dd",
            "4932caff0ff746eab6f01bf08b70ac45",
        )
        self.assertEqual(actual, "ea1db114af3d7062874693fa044f4ff8")

    def test_av_url_reaches_view_pipeline(self):
        view = {
            "data": {
                "bvid": self.info.media_id,
                "aid": self.info.aid,
                "title": self.info.title,
                "owner": {"name": self.info.author, "mid": 1},
                "pages": [{"page": 1, "cid": 42, "part": "P1", "duration": 1}],
            }
        }
        part = VideoResult(
            info=SimpleNamespace(bili_page=self.page),
            output_path=Path("example.mp4"),
            size_bytes=1,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "dydownload.pipeline.fetch_view", return_value=view,
        ) as fetch_view_mock, patch(
            "dydownload.pipeline._download_bilibili_page", return_value=part,
        ):
            result = download_bilibili(
                "https://www.bilibili.com/video/av170001",
                "SESSDATA=test",
                output_dir=Path(tmp),
            )
        fetch_view_mock.assert_called_once()
        self.assertEqual(result.bilibili.info.media_id, self.info.media_id)

    def test_single_stream_output_has_dot_extension(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "dydownload.pipeline.fetch_playurl", return_value={},
        ), patch(
            "dydownload.pipeline.pick_streams",
            return_value={
                "kind": "single",
                "url": "https://cdn.example/video.mp4",
                "width": 1920,
                "height": 1080,
            },
        ), patch(
            "dydownload.pipeline.download_video",
            side_effect=lambda _url, path, **_kwargs: path.write_bytes(b"x"),
        ):
            result = _download_bilibili_page(
                self.info,
                self.page,
                1,
                1,
                Path(tmp),
                "SESSDATA=test",
                80,
                False,
                True,
                None,
            )
        self.assertEqual(result.output_path.suffix, ".mp4")

    def test_dash_without_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "dydownload.pipeline.fetch_playurl", return_value={},
        ), patch(
            "dydownload.pipeline.pick_streams",
            return_value={
                "kind": "dash",
                "video_url": "https://cdn.example/video.m4s",
                "audio_url": "",
            },
        ):
            with self.assertRaisesRegex(BilibiliAPIError, "缺少音频轨"):
                _download_bilibili_page(
                    self.info,
                    self.page,
                    1,
                    1,
                    Path(tmp),
                    "SESSDATA=test",
                    80,
                    True,
                    True,
                    None,
                )

    def test_result_paths_include_dash_companion_audio(self):
        video = Path("video.m4s")
        audio = Path("audio.m4s")
        part = VideoResult(
            info=SimpleNamespace(),
            output_path=video,
            size_bytes=2,
            extra_paths=[audio],
        )
        result = DownloadResult(
            bilibili=BilibiliResult(info=self.info, parts=[part], size_bytes=2)
        )
        self.assertEqual(result.paths, [video, audio])


class DownloadConcurrencyTests(unittest.TestCase):
    def test_shared_output_directory_serializes_whole_pipelines(self):
        state_lock = threading.Lock()
        active = 0
        maximum = 0

        def fake_pipeline(*_args, **_kwargs):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return DownloadResult()

        with tempfile.TemporaryDirectory() as tmp, patch(
            "dydownload.pipeline._download_media_unlocked",
            side_effect=fake_pipeline,
        ):
            threads = [
                threading.Thread(
                    target=download_media,
                    args=(f"https://example/{index}", "cookie"),
                    kwargs={"output_dir": Path(tmp), "platform": "douyin"},
                )
                for index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(maximum, 1)


class CookieStatusTests(unittest.TestCase):
    def test_bilibili_api_failure_is_unknown_not_expired(self):
        with patch(
            "dydownload.bilibili.api_client.probe_cookie",
            side_effect=BilibiliAPIError("offline"),
        ):
            status = probe_cookie_freshness(
                "SESSDATA=test", platform="bilibili"
            )
        self.assertEqual(status, CookieStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
