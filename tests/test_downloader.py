"""Local HTTP integration tests for download resume behavior."""

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dydownload.downloader import download_video


_PAYLOAD = b"abcdef"


class _RangeHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(_PAYLOAD)))
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range", "")
        if range_header == "bytes=3-":
            body = _PAYLOAD[3:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", "bytes 3-5/6")
        else:
            body = _PAYLOAD
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class DownloaderResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _RangeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/media"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_valid_content_range_resumes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "video.mp4"
            output.with_suffix(".mp4.part").write_bytes(_PAYLOAD[:3])
            download_video(self.url, output, max_retries=1)
            self.assertEqual(output.read_bytes(), _PAYLOAD)
            self.assertFalse(output.with_suffix(".mp4.part").exists())

    def test_equal_size_stale_part_is_restarted(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "video.mp4"
            output.with_suffix(".mp4.part").write_bytes(b"XXXXXX")
            download_video(self.url, output, max_retries=1)
            self.assertEqual(output.read_bytes(), _PAYLOAD)


if __name__ == "__main__":
    unittest.main()
