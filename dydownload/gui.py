"""tkinter GUI for dydownload — 双击即可启动，无需命令行。"""

import random
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
        from dydownload.api_client import (
            CookieExpiredError,
            DouyinAPIError,
            VideoNotFoundError,
        )
        from dydownload.pipeline import download_aweme

        try:
            # ── Check cookies ──
            cookie_info = load_cookies()
            if cookie_info.status == CookieStatus.MISSING:
                self._dl_fail("Cookie 未就绪，请在浏览器中登录抖音后点击插件图标推送 Cookie")
                return

            cookie_str = cookie_info.cookie_string
            self._log_msg("解析作品链接...")

            def on_event(name, payload):
                if name == "phase":
                    self._log_msg(payload)
                    self._root_call(lambda t=payload: self._prog_text.set(t))
                elif name == "info":
                    self._log_msg(
                        f"作者: @{payload['author']} ({payload['nickname']})"
                    )
                    if payload["desc"]:
                        self._log_msg(f"描述: {payload['desc'][:60]}")
                    if payload["media_type"] == "image":
                        self._log_msg(
                            f"检测到图文/图集，共 {payload['image_count']} 张图片"
                            + ("（含 BGM）" if payload["has_bgm"] else "")
                        )
                elif name == "file":
                    idx = payload["index"]
                    total = payload["total"]
                    fname = payload["name"]
                    if payload["status"] == "downloading":
                        if payload.get("size"):
                            pct = payload["downloaded"] / payload["size"] * 100
                            self._root_call(
                                lambda p=pct, f=fname: self._progress.configure(value=p)
                            )
                            self._root_call(
                                lambda f=fname, d=payload['downloaded'], s=payload['size']:
                                self._prog_text.set(
                                    f"下载 {f}: {d/1024:.1f}/{s/1024:.1f} KB"
                                )
                            )
                        else:
                            self._root_call(
                                lambda i=idx, t=total, f=fname:
                                self._prog_text.set(f"下载 {f} ({i}/{t})")
                            )
                    elif payload["status"] == "done":
                        self._log_msg(f"  ✓ {fname}")
                    elif payload["status"] == "error":
                        self._log_msg(f"  ✗ {fname} 失败")
                elif name == "done":
                    self._root_call(lambda: self._progress.configure(value=100))
                    if payload.video:
                        v = payload.video
                        size_mb = v.size_bytes / 1024 / 1024
                        self._log_msg(f"✓ 视频下载完成: {v.output_path.name} ({size_mb:.1f} MB)")
                        self._root_call(
                            lambda v=v: self._prog_text.set(
                                f"✓ 完成: {v.output_path.name} ({v.size_bytes/1024/1024:.1f} MB)"
                            )
                        )
                    elif payload.image:
                        img = payload.image
                        size_mb = img.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"✓ 图集下载完成 ({len(img.files)} 个文件, {size_mb:.1f} MB)"
                        )
                        self._log_msg(f"  {img.folder}")
                        self._root_call(
                            lambda img=img: self._prog_text.set(
                                f"✓ 图集完成 ({len(img.files)} 文件)"
                            )
                        )

            try:
                download_aweme(raw_url, cookie_str, output_dir=DOWNLOAD_DIR, on_event=on_event)
            except CookieExpiredError:
                self._dl_fail("Cookie 已过期，请重新登录抖音并推送 Cookie")
                return
            except VideoNotFoundError as e:
                self._dl_fail(f"作品不可用: {e}")
                return
            except DouyinAPIError as e:
                self._dl_fail(f"API 错误: {e}")
                return

            self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))

        except Exception as e:
            self._dl_fail(f"{type(e).__name__}: {e}")

    def _on_progress(self, downloaded, total, status=None):
        """Legacy video progress hook. Kept for compatibility — the pipeline
        now drives progress through on_event; this is a no-op stub."""
        _ = (downloaded, total, status)

    def _dl_fail(self, msg):
        self._log_msg(f"[错误] {msg}")
        self._root_call(lambda: self._prog_text.set(f"✗ {msg}"))
        self._root_call(lambda: self._progress.configure(value=0))
        self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))

    def _root_call(self, fn):
        """Schedule fn to run on the main tk thread."""
        self.root.after(0, fn)

    # ── Utils ──

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
