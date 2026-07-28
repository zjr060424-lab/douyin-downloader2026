"""Regression tests for DASH muxing on Windows paths."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dydownload.mux import mux_dash


class MuxPathTests(unittest.TestCase):
    def test_unicode_paths_are_not_passed_to_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "中文标题_video.m4s"
            audio = root / "中文标题_audio.m4s"
            output = root / "中文标题.mp4"
            video.write_bytes(b"video")
            audio.write_bytes(b"audio")

            def fake_run(args, **kwargs):
                self.assertTrue(all(str(arg).isascii() for arg in args))
                self.assertEqual(args[-1], "output.mp4")
                (Path(kwargs["cwd"]) / args[-1]).write_bytes(b"muxed")
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch("dydownload.mux.subprocess.run", side_effect=fake_run):
                result = mux_dash(
                    video, audio, output, ffmpeg="C:/ffmpeg/ffmpeg.exe"
                )

            self.assertEqual(result, output.resolve())
            self.assertEqual(output.read_bytes(), b"muxed")


if __name__ == "__main__":
    unittest.main()
