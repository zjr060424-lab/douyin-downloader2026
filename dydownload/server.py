"""Minimal HTTP server to receive cookies from the browser extension."""

import json
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler

from dydownload.config import (
    BILI_COOKIE_FILE,
    COOKIE_DIR,
    COOKIE_FILE,
    NETSCAPE_COOKIE_FILE,
    SERVER_PORTS,
)
from dydownload.cookie_manager import (
    CookieStatus,
    load_bilibili_cookies,
    load_cookies,
)

_download_tasks: dict[str, dict] = {}
_download_lock = threading.Lock()


class CookieReceiverHandler(BaseHTTPRequestHandler):
    """HTTP handler that accepts POST /cookie with JSON body."""

    def do_POST(self):
        if self.path == "/cookie":
            self._handle_cookie()
        elif self.path == "/cookie/bilibili":
            self._handle_cookie(platform="bilibili")
        elif self.path == "/download":
            self._handle_download()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_cookie(self, platform: str = "douyin"):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            cookie_string = data.get("cookie", "")
            netscape_string = data.get("netscape", "")
            target_file = BILI_COOKIE_FILE if platform == "bilibili" else COOKIE_FILE

            if cookie_string:
                COOKIE_DIR.mkdir(parents=True, exist_ok=True)
                target_file.write_text(cookie_string, encoding="utf-8")

            if netscape_string and platform == "douyin":
                NETSCAPE_COOKIE_FILE.write_text(netscape_string, encoding="utf-8")

            cookie_count = len(cookie_string.split(";")) if cookie_string else 0

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "status": "ok",
                    "platform": platform,
                    "count": cookie_count,
                    "netscape_saved": bool(netscape_string) and platform == "douyin",
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

            platform = (data.get("platform") or "auto").lower()
            try:
                from dydownload.pipeline import detect_platform
                resolved = (
                    detect_platform(url) if platform == "auto" else platform
                )
            except ValueError as exc:
                self._json_response(400, {"status": "error", "message": str(exc)})
                return

            if resolved == "bilibili":
                cookie_info = load_bilibili_cookies()
                ck_missing = (
                    "Cookie 未就绪，请先登录 B 站并推送 Cookie "
                    "(SESSDATA/bili_jct/buvid3)"
                )
            else:
                cookie_info = load_cookies()
                ck_missing = "Cookie 未就绪，请先登录抖音并推送 Cookie"
            if cookie_info.status == CookieStatus.MISSING:
                self._json_response(400, {"status": "error", "message": ck_missing})
                return

            import uuid
            task_id = uuid.uuid4().hex[:8]
            with _download_lock:
                _download_tasks[task_id] = {
                    "status": "downloading",
                    "url": url,
                    "platform": resolved,
                }

            thread = threading.Thread(
                target=_run_download,
                args=(task_id, url, cookie_info.cookie_string, resolved, data),
                daemon=True,
            )
            thread.start()

            self._json_response(200, {
                "status": "started",
                "task_id": task_id,
                "platform": resolved,
                "message": "下载已开始",
            })

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
                "bilibili_cookie_available": BILI_COOKIE_FILE.exists(),
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


def _run_download(task_id: str, url: str, cookie_str: str, platform: str, data: dict):
    """Execute the full download pipeline in a background thread."""
    from dydownload.api_client import (
        CookieExpiredError,
        DouyinAPIError,
        VideoNotFoundError,
    )
    from dydownload.bilibili.api_client import (
        BangumiNotSupportedError,
        BilibiliAPIError,
        BilibiliCookieExpiredError,
        BilibiliNotFoundError,
    )
    from dydownload.pipeline import download_media

    def on_event(name, payload):
        with _download_lock:
            bucket = _download_tasks.setdefault(task_id, {})
            if name == "info":
                bucket["info"] = {
                    "media_type": payload.get("media_type"),
                    "platform": payload.get("platform"),
                    "title": payload.get("title") or payload.get("desc"),
                    "author": payload.get("author") or payload.get("nickname"),
                    "desc": payload.get("desc"),
                    "image_count": payload.get("image_count", 0),
                    "pages": payload.get("pages", 0),
                }
            elif name == "part":
                bucket["part"] = {
                    "index": payload.get("index"),
                    "total": payload.get("total"),
                    "title": payload.get("title"),
                }
            elif name == "file" and payload.get("status") == "downloading":
                bucket["progress"] = {
                    "name": payload.get("name"),
                    "index": payload.get("index"),
                    "total": payload.get("total"),
                    "downloaded": payload.get("downloaded", 0),
                    "size": payload.get("size", 0),
                }
            elif name == "file" and payload.get("status") == "done":
                bucket.setdefault("files", []).append({
                    "name": payload.get("name"),
                    "path": payload.get("path"),
                    "size": payload.get("size") or payload.get("downloaded") or 0,
                })
            elif name == "done":
                bucket["done"] = True

    try:
        result = download_media(
            url,
            cookie_str,
            on_event=on_event,
            platform=platform,
            qn=int(data.get("quality", 80) or 80),
            prefer_dash=bool(data.get("prefer_dash", True)),
            multi_part_mode=str(data.get("parts", "all") or "all"),
            mux=bool(data.get("mux", True)),
        )
        if result.video:
            v = result.video
            with _download_lock:
                _download_tasks[task_id] = {
                    "status": "done",
                    "kind": "video",
                    "platform": platform,
                    "file": str(v.output_path),
                    "size": v.size_bytes,
                    "title": v.info.desc or "",
                    "author": v.info.author_unique_id,
                }
        elif result.image:
            img = result.image
            with _download_lock:
                _download_tasks[task_id] = {
                    "status": "done",
                    "kind": "image",
                    "platform": platform,
                    "folder": str(img.folder),
                    "files": [str(p) for p in img.files],
                    "size": img.size_bytes,
                    "title": img.info.desc or "",
                    "author": img.info.author_unique_id,
                    "image_count": len(img.info.images),
                }
        elif result.bilibili:
            bili = result.bilibili
            with _download_lock:
                _download_tasks[task_id] = {
                    "status": "done",
                    "kind": "bilibili",
                    "platform": "bilibili",
                    "title": bili.info.title,
                    "author": bili.info.author,
                    "files": [
                        {
                            "name": p.output_path.name,
                            "path": str(p.output_path),
                            "size": p.size_bytes,
                        }
                        for p in bili.parts
                    ],
                    "size": bili.size_bytes,
                    "pages": [
                        {
                            "page": p.info.bili_page.page,
                            "title": p.info.bili_page.part_title or bili.info.title,
                            "file": str(p.output_path),
                        }
                        for p in bili.parts
                    ],
                }
        else:
            with _download_lock:
                _download_tasks[task_id] = {
                    "status": "error",
                    "platform": platform,
                    "message": "未生成任何文件",
                }

    except BangumiNotSupportedError as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "platform": platform, "message": str(e)}
    except BilibiliCookieExpiredError:
        with _download_lock:
            _download_tasks[task_id] = {
                "status": "error",
                "platform": "bilibili",
                "message": "B站 Cookie 过期，请重新登录并推送 SESSDATA",
            }
    except BilibiliNotFoundError as e:
        with _download_lock:
            _download_tasks[task_id] = {
                "status": "error",
                "platform": "bilibili",
                "message": f"作品不可用: {e}",
            }
    except BilibiliAPIError as e:
        with _download_lock:
            _download_tasks[task_id] = {
                "status": "error",
                "platform": "bilibili",
                "message": str(e),
            }
    except CookieExpiredError:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "platform": platform, "message": "Cookie 已过期，请重新推送"}
    except VideoNotFoundError as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "platform": platform, "message": f"作品不可用: {e}"}
    except DouyinAPIError as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "platform": platform, "message": str(e)}
    except Exception as e:
        with _download_lock:
            _download_tasks[task_id] = {"status": "error", "platform": platform, "message": f"{type(e).__name__}: {e}"}
