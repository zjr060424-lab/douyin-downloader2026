"""tkinter GUI for dydownload — 双击即可启动，无需命令行。"""

import random
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

_TRACE_FILE = Path.home() / ".dydownload" / "startup.log"

def _trace(msg: str) -> None:
    """Write startup trace to file for debugging silent crashes."""
    try:
        _TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

_trace("=== dydownload startup ===")

# ── Startup crash guard ──
_startup_ok = True
try:
    from dydownload.config import (
        COOKIE_FILE,
        DOWNLOAD_DIR,
        KEY_COOKIE_NAMES,
        LOCAL_SERVER_HOST,
        USER_AGENTS,
    )
    from dydownload.cookie_manager import load_cookies, probe_cookie_freshness, CookieStatus
    from dydownload.server import start_server
except Exception:
    _startup_ok = False
    import traceback as _traceback
    _log_path = Path.home() / ".dydownload" / "crash.log"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(_log_path, "w", encoding="utf-8") as _f:
        _f.write(f"dydownload 导入失败\n{'=' * 50}\n")
        _traceback.print_exc(file=_f)
    raise


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("dydownload — 抖音无水印视频下载")
        self.root.geometry("560x520")
        self.root.minsize(480, 420)
        self.root.resizable(True, True)

        self.server = None
        self.server_port = None
        self._download_thread = None
        self._closing = False

        self._build_ui()
        self._start_server()
        self._refresh_cookie_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── UI construction ──

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # ── Server status ──
        frame_server = ttk.LabelFrame(self.root, text="服务状态", padding=8)
        frame_server.pack(fill="x", **pad)

        self._sv_status = tk.StringVar(value="启动中...")
        ttk.Label(frame_server, textvariable=self._sv_status, foreground="#2a2").pack(anchor="w")

        # ── Cookie status ──
        frame_ck = ttk.LabelFrame(self.root, text="Cookie 状态", padding=8)
        frame_ck.pack(fill="x", **pad)

        self._ck_status = tk.StringVar(value="检测中...")
        ttk.Label(frame_ck, textvariable=self._ck_status).pack(anchor="w")

        self._ck_details = tk.Text(frame_ck, height=3, width=60, state="disabled",
                                    font=("Microsoft YaHei UI", 9))
        self._ck_details.pack(fill="x", pady=(4, 0))

        # ── URL input ──
        frame_url = ttk.LabelFrame(self.root, text="下载视频", padding=8)
        frame_url.pack(fill="x", **pad)

        row_url = ttk.Frame(frame_url)
        row_url.pack(fill="x")
        self._url_var = tk.StringVar()
        ttk.Entry(row_url, textvariable=self._url_var, font=("Microsoft YaHei UI", 10)).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        self._btn_dl = ttk.Button(row_url, text="下载", command=self._start_download)
        self._btn_dl.pack(side="right")

        # ── Progress ──
        self._progress = ttk.Progressbar(self.root, mode="determinate", length=500)
        self._progress.pack(fill="x", padx=20, pady=(8, 2))

        self._prog_text = tk.StringVar(value="等待任务...")
        ttk.Label(self.root, textvariable=self._prog_text, font=("Microsoft YaHei UI", 9)).pack(anchor="center")

        # ── Output dir ──
        frame_out = ttk.Frame(self.root)
        frame_out.pack(fill="x", padx=20, pady=(8, 2))
        ttk.Label(frame_out, text=f"保存位置: {DOWNLOAD_DIR}", foreground="#666").pack(side="left")
        ttk.Button(frame_out, text="打开目录", command=self._open_output_dir).pack(side="right")

        # ── Log ──
        frame_log = ttk.LabelFrame(self.root, text="日志", padding=4)
        frame_log.pack(fill="both", expand=True, **pad)

        self._log = tk.Text(frame_log, height=6, state="disabled",
                            font=("Microsoft YaHei UI", 9), wrap="word")
        scrollbar = ttk.Scrollbar(frame_log, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ── Server ──

    def _start_server(self):
        try:
            self.server, self.server_port, _ = start_server()
            self._sv_status.set(f"✓ 服务运行中 — 端口 {self.server_port}")
            self._log_msg(f"Cookie 接收服务已启动 (127.0.0.1:{self.server_port})")
            self._log_msg("浏览器插件可以开始推送 Cookie 了")
        except Exception as e:
            self._sv_status.set(f"✗ 服务启动失败: {e}")
            self._log_msg(f"[错误] 服务启动失败: {e}")

    def _refresh_cookie_status(self):
        info = load_cookies()
        if info.status == CookieStatus.MISSING:
            self._ck_status.set("✗ Cookie 未就绪")
            self._update_ck_details("请在浏览器中打开抖音并登录，然后点击插件图标推送 Cookie")
        else:
            freshness = probe_cookie_freshness(info.cookie_string)
            display = {"valid": "有效 ✓", "expired": "已过期 ✗", "unknown": "未知"}
            self._ck_status.set(f"Cookie 已加载 ({len(info.key_cookies)} 个关键字段) — {display.get(freshness, freshness)}")
            lines = []
            for name in KEY_COOKIE_NAMES:
                mark = "✓" if name in info.key_cookies else "✗"
                lines.append(f"  {mark}  {name}")
            self._update_ck_details("\n".join(lines))
        self.root.after(30_000, self._refresh_cookie_status)

    def _update_ck_details(self, text):
        self._ck_details.configure(state="normal")
        self._ck_details.delete("1.0", "end")
        self._ck_details.insert("1.0", text)
        self._ck_details.configure(state="disabled")

    # ── Download ──

    def _start_download(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先粘贴抖音视频链接")
            return

        self._btn_dl.configure(state="disabled", text="下载中...")
        self._progress.configure(value=0)
        self._prog_text.set("准备下载...")

        thread = threading.Thread(target=self._do_download, args=(url,), daemon=True)
        thread.start()

    def _do_download(self, raw_url: str):
        import httpx
        from dydownload.api_client import (
            fetch_video_page, fetch_aweme_detail,
            DouyinAPIError, CookieExpiredError, VideoNotFoundError,
        )
        from dydownload.signature import extract_webid
        from dydownload.video_parser import parse_from_aweme_detail
        from dydownload.downloader import download_video

        try:
            # ── Check cookies ──
            cookie_info = load_cookies()
            if cookie_info.status == CookieStatus.MISSING:
                self._dl_fail("Cookie 未就绪，请在浏览器中登录抖音后点击插件图标推送 Cookie")
                return

            cookie_str = cookie_info.cookie_string

            # ── Resolve short link ──
            url = self._extract_url(raw_url)
            if "v.douyin.com" in url:
                self._log_msg("解析短链接...")
                with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                    resp = client.get(url)
                    if resp.status_code in (301, 302):
                        url = resp.headers.get("Location", url)

            # ── Extract video ID ──
            video_id = ""
            m = re.search(r"video/(\d+)", url)
            if m:
                video_id = m.group(1)
            else:
                m = re.search(r"(\d{15,25})", url)
                if m:
                    video_id = m.group(1)

            if not video_id:
                self._dl_fail("无法从链接中提取视频 ID，请检查链接格式")
                return

            self._log_msg(f"Video ID: {video_id}")
            ua = random.choice(USER_AGENTS)

            # ── Step 1: Get video page ──
            self._log_msg("获取视频页面...")
            try:
                html = fetch_video_page(video_id, cookie_str, debug=False)
            except CookieExpiredError:
                self._dl_fail("Cookie 已过期，请重新登录抖音并推送 Cookie")
                return
            except DouyinAPIError as e:
                self._dl_fail(str(e))
                return

            webid = extract_webid(html)
            if not webid:
                m2 = re.search(r'"user_unique_id"\s*:\s*"(\d+)"', html)
                if m2:
                    webid = m2.group(1)

            # ── Step 2: API ──
            self._log_msg("调用抖音 API (a_bogus 签名)...")
            try:
                data = fetch_aweme_detail(video_id, cookie_string=cookie_str, webid=webid or "", user_agent=ua)
            except VideoNotFoundError as e:
                self._dl_fail(f"视频不可用: {e}")
                return
            except DouyinAPIError as e:
                self._dl_fail(f"API 错误: {e}")
                return

            vinfo = parse_from_aweme_detail(data)
            if not vinfo:
                self._dl_fail("无法解析视频数据")
                return

            media_url = vinfo.no_watermark_url
            if not media_url:
                self._dl_fail("没有可用的无水印视频地址")
                return

            # ── Step 3: Download ──
            safe_title = re.sub(r'[\x00-\x1f\\/*?:"<>|]', '',
                                vinfo.desc[:80] if vinfo.desc else "douyin").strip()
            filename = f"{safe_title}-{vinfo.video_id}.mp4"
            output_path = DOWNLOAD_DIR / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self._log_msg(f"开始下载: {filename}")
            self._log_msg(f"作者: @{vinfo.author_unique_id}")
            self._root_call(lambda: self._prog_text.set(f"下载中: {filename}"))

            download_headers = {
                "Referer": f"https://www.douyin.com/video/{video_id}/",
                "User-Agent": ua,
            }

            download_video(
                media_url, output_path,
                headers=download_headers,
                progress_callback=self._on_progress,
            )

            size_mb = output_path.stat().st_size / 1024 / 1024
            self._log_msg(f"✓ 下载完成: {filename} ({size_mb:.1f} MB)")
            self._root_call(lambda: self._prog_text.set(f"✓ 下载完成: {filename} ({size_mb:.1f} MB)"))
            self._root_call(lambda: self._progress.configure(value=100))
            self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))

        except Exception as e:
            self._dl_fail(f"{type(e).__name__}: {e}")

    def _on_progress(self, downloaded, total, status=None):
        """Called from download thread — schedule UI update on main thread."""
        if status == "done":
            self._root_call(lambda: self._progress.configure(value=100))
            return
        if total > 0:
            pct = min(int(downloaded / total * 100), 100)
            self._root_call(lambda p=pct: self._progress.configure(value=p))
            mb_dl = downloaded / 1024 / 1024
            mb_total = total / 1024 / 1024
            self._root_call(lambda: self._prog_text.set(
                f"下载中... {mb_dl:.1f} / {mb_total:.1f} MB"))

    def _dl_fail(self, msg):
        self._log_msg(f"[错误] {msg}")
        self._root_call(lambda: self._prog_text.set(f"✗ {msg}"))
        self._root_call(lambda: self._progress.configure(value=0))
        self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))

    def _root_call(self, fn):
        """Schedule fn to run on the main tk thread."""
        self.root.after(0, fn)

    # ── Utils ──

    @staticmethod
    def _extract_url(text: str) -> str:
        patterns = [
            r'https?://v\.douyin\.com/\S+',
            r'https?://www\.douyin\.com/video/\d+',
            r'https?://www\.iesdouyin\.com/share/video/\d+',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(0).rstrip('/')
        return text

    def _open_output_dir(self):
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(DOWNLOAD_DIR))

    def _log_msg(self, msg):
        self._root_call(lambda: self._append_log(msg))

    def _append_log(self, msg):
        self._log.configure(state="normal")
        self._log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Shutdown ──

    def _on_close(self):
        if messagebox.askokcancel("退出", "确定要退出 dydownload 吗？\n后端服务将停止。"):
            self._closing = True
            if self.server:
                self.server.shutdown()
            self.root.destroy()


def _write_crash_log():
    import traceback
    log_path = Path.home() / ".dydownload" / "crash.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"dydownload 启动失败\n{'=' * 50}\n")
        traceback.print_exc(file=f)
    try:
        import tkinter.messagebox as mb
        mb.showerror("dydownload 启动失败", f"详见 {log_path}")
    except Exception:
        pass


def main():
    try:
        App()
    except Exception:
        _write_crash_log()


if __name__ == "__main__":
    main()
