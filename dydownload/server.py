"""Minimal HTTP server to receive cookies from the browser extension."""

import json
import re
import random
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from dydownload.config import (
    COOKIE_DIR, COOKIE_FILE, NETSCAPE_COOKIE_FILE, SERVER_PORTS, USER_AGENTS,
)
from dydownload.cookie_manager import load_cookies, CookieStatus

_download_tasks: dict[str, dict] = {}
_download_lock = threading.Lock()


class CookieReceiverHandler(BaseHTTPRequestHandler):
    """HTTP handler that accepts POST /cookie with JSON body."""

    def do_POST(self):
        if self.path == "/cookie":
            self._handle_cookie()
        elif self.path == "/download":
            self._handle_download()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_cookie(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            cookie_string = data.get("cookie", "")
            netscape_string = data.get("netscape", "")

            if cookie_string:
                COOKIE_DIR.mkdir(parents=True, exist_ok=True)
                COOKIE_FILE.write_text(cookie_string, encoding="utf-8")

            if netscape_string:
                NETSCAPE_COOKIE_FILE.write_text(netscape_string, encoding="utf-8")

            cookie_count = len(cookie_string.split(";")) if cookie_string else 0

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "status": "ok",
                    "count": cookie_count,
                    "netscape_saved": bool(netscape_string),
                }).encode()
            )
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())

    def _handle_download(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            url = data.get("url", "").strip()

            if not url:
                self._json_response(400, {"status": "error", "message": "缺少 url 参数"})
                return

            cookie_info = load_cookies()
            if cookie_info.status == CookieStatus.MISSING:
                self._json_response(400, {"status": "error", "message": "Cookie 未就绪，请先登录抖音并推送 Cookie"})
                return

            import uuid
            task_id = uuid.uuid4().hex[:8]
            with _download_lock:
                _download_tasks[task_id] = {"status": "downloading", "url": url}

            thread = threading.Thread(
                target=_run_download, args=(task_id, url, cookie_info.cookie_string), daemon=True
            )
            thread.start()

            self._json_response(200, {"status": "started", "task_id": task_id, "message": "下载已开始"})

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Health check and download status endpoints."""
        if self.path == "/health":
            self._json_response(200, {
                "status": "running",
                "cookie_available": COOKIE_FILE.exists(),
            })
        elif self.path.startswith("/download/status"):
            task_id = self.path.split("/")[-1]
            with _download_lock:
                task = _download_tasks.get(task_id)
            if task:
                self._json_response(200, task)
            else:
                self._json_response(404, {"status": "not_found"})
        elif self.path.startswith("/download/list"):
            with _download_lock:
                tasks = list(_download_tasks.values())
            self._json_response(200, {"tasks": tasks})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging — we use rich console instead."""
        pass


def _find_available_port() -> int:
    """Find the first available port from SERVER_PORTS."""
    for port in SERVER_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return SERVER_PORTS[0]  # fallback — will error on bind if all taken


def start_server(host: str = "127.0.0.1", port: int | None = None) -> tuple[HTTPServer, int, threading.Event]:
    """Start the cookie receiver server in a daemon thread.

    Args:
        host: Bind address (default 127.0.0.1).
        port: Preferred port. If None or occupied, auto-select from pool.

    Returns:
        Tuple of (server, actual_port, ready_event).
        ready_event is set once the server is accepting connections.
    """
    if port is None:
        port = _find_available_port()

    ready_event = threading.Event()

    # Retry with next port if the preferred one is taken
    server = None
    for attempt_port in ([port] + [p for p in SERVER_PORTS if p != port]):
        try:
            server = HTTPServer((host, attempt_port), CookieReceiverHandler)
            port = attempt_port
            break
        except OSError:
            continue

    if server is None:
        raise RuntimeError(f"无法在 {host}:{SERVER_PORTS} 范围内启动服务")

    thread = threading.Thread(target=_serve, args=(server, ready_event), daemon=True)
    thread.start()
    ready_event.wait(timeout=2.0)

    return server, port, ready_event


def _serve(server: HTTPServer, ready_event: threading.Event):
    """Run the server and signal readiness."""
    ready_event.set()
    server.serve_forever()


def _run_download(task_id: str, url: str, cookie_str: str):
    """Execute the full download pipeline in a background thread."""
    import httpx
    from dydownload.api_client import (
        fetch_video_page, fetch_aweme_detail,
        DouyinAPIError, CookieExpiredError, VideoNotFoundError,
    )
    from dydownload.signature import extract_webid
    from dydownload.video_parser import parse_from_aweme_detail
    from dydownload.downloader import download_video
    from dydownload.config import DOWNLOAD_DIR

    try:
        ua = random.choice(USER_AGENTS)

        # Resolve short link
        if "v.douyin.com" in url:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                resp = client.get(url)
                if resp.status_code in (301, 302):
                    url = resp.headers.get("Location", url)

        # Extract video ID
        m = re.search(r"video/(\d+)", url)
        video_id = m.group(1) if m else ""
        if not video_id:
            m = re.search(r"(\d{15,25})", url)
            video_id = m.group(1) if m else ""

        if not video_id:
            with _download_lock:
                _download_tasks[task_id] = {"status": "error", "message": "无法从 URL 提取视频 ID"}
            return

        # Step 1: get video page + webid
        html = fetch_video_page(video_id, cookie_str)
        webid = extract_webid(html)
        if not webid:
            m2 = re.search(r'"user_unique_id"\s*:\s*"(\d+)"', html)
            if m2:
                webid = m2.group(1)

        # Step 2: API with a_bogus
        data = fetch_aweme_detail(video_id, cookie_string=cookie_str, webid=webid or "", user_agent=ua)
        vinfo = parse_from_aweme_detail(data)
        if not vinfo:
            with _download_lock:
                _download_tasks[task_id] = {"status": "error", "message": "无法解析视频数据"}
            return

        media_url = vinfo.no_watermark_url
        if not media_url:
            with _download_lock:
                _download_tasks[task_id] = {"status": "error", "message": "没有无水印 URL"}
            return

        # Step 3: download
        safe_title = re.sub(r'[\x00-\x1f\\/*?:"<>|]', '', vinfo.desc[:80] if vinfo.desc else "douyin").strip()
        filename = f"{safe_title}-{vinfo.video_id}.mp4"
        output_path = DOWNLOAD_DIR / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        download_headers = {
            "Referer": f"https://www.douyin.com/video/{video_id}/",
            "User-Agent": ua,
        }
        download_video(media_url, output_path, headers=download_headers)

        with _download_lock:
            _download_tasks[task_id] = {
                "status": "done",
                "file": str(output_path),
                "size": output_path.stat().st_size,
                "title": safe_title,
                "author": vinfo.author_unique_id,
            }

    except CookieExpiredError:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "message": "Cookie 已过期，请重新推送"}
    except DouyinAPIError as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "message": str(e)}
    except Exception as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "message": f"{type(e).__name__}: {e}"}
