"""tkinter GUI for dydownload — 抖音 + B 站 双平台下载。"""

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
        BILI_COOKIE_FILE,
        COOKIE_FILE,
        DOWNLOAD_DIR,
        KEY_COOKIE_NAMES,
        KEY_COOKIE_NAMES_BILI,
        LOCAL_SERVER_HOST,
    )
    from dydownload.cookie_manager import (
        CookieStatus,
        load_bilibili_cookies,
        load_cookies,
        probe_cookie_freshness,
    )
    from dydownload.mux import find_ffmpeg
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
    PLATFORM_OPTIONS = ("自动", "抖音", "Bilibili")
    QUALITY_OPTIONS = ("36", "48", "64", "80", "112", "116", "120")

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("dydownload — 抖音 / B 站下载")
        self.root.geometry("640x640")
        self.root.minsize(520, 500)
        self.root.resizable(True, True)

        self.server = None
        self.server_port = None
        self._download_thread = None
        self._closing = False
        self._ffmpeg_available = bool(find_ffmpeg())

        self._build_ui()
        self._start_server()
        self._refresh_cookie_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── UI construction ──

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        frame_server = ttk.LabelFrame(self.root, text="服务状态", padding=8)
        frame_server.pack(fill="x", **pad)
        self._sv_status = tk.StringVar(value="启动中...")
        ttk.Label(frame_server, textvariable=self._sv_status, foreground="#2a2").pack(anchor="w")

        frame_ck = ttk.LabelFrame(self.root, text="Cookie 状态", padding=8)
        frame_ck.pack(fill="x", **pad)
        self._ck_status = tk.StringVar(value="检测中...")
        ttk.Label(frame_ck, textvariable=self._ck_status).pack(anchor="w")
        self._ck_details = tk.Text(
            frame_ck, height=5, width=60, state="disabled",
            font=("Microsoft YaHei UI", 9),
        )
        self._ck_details.pack(fill="x", pady=(4, 0))

        frame_url = ttk.LabelFrame(self.root, text="下载", padding=8)
        frame_url.pack(fill="x", **pad)

        row_url = ttk.Frame(frame_url)
        row_url.pack(fill="x")
        self._url_var = tk.StringVar()
        ttk.Entry(row_url, textvariable=self._url_var, font=("Microsoft YaHei UI", 10)).pack(
            side="left", fill="x", expand=True, padx=(0, 8),
        )
        self._btn_dl = ttk.Button(row_url, text="下载", command=self._start_download)
        self._btn_dl.pack(side="right")

        opts = ttk.Frame(frame_url)
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text="平台:").grid(row=0, column=0, sticky="w")
        self._platform_var = tk.StringVar(value=self.PLATFORM_OPTIONS[0])
        ttk.Combobox(
            opts, textvariable=self._platform_var,
            values=self.PLATFORM_OPTIONS, state="readonly", width=8,
        ).grid(row=0, column=1, padx=(4, 12), sticky="w")

        ttk.Label(opts, text="画质:").grid(row=0, column=2, sticky="w")
        self._quality_var = tk.StringVar(value="80")
        ttk.Combobox(
            opts, textvariable=self._quality_var,
            values=self.QUALITY_OPTIONS, state="readonly", width=6,
        ).grid(row=0, column=3, padx=(4, 12), sticky="w")

        self._dash_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="优先 DASH", variable=self._dash_var).grid(
            row=0, column=4, padx=(4, 12), sticky="w",
        )

        self._parts_var = tk.StringVar(value="all")
        ttk.Label(opts, text="多P:").grid(row=0, column=5, sticky="w")
        ttk.Combobox(
            opts, textvariable=self._parts_var,
            values=("all", "first"), state="readonly", width=6,
        ).grid(row=0, column=6, padx=(4, 0), sticky="w")

        self._mux_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="ffmpeg 合流", variable=self._mux_var,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        if not self._ffmpeg_available:
            self._mux_var.set(False)
            ttk.Label(
                opts, text="(未找到 ffmpeg，关闭合流)",
                foreground="#999",
            ).grid(row=1, column=3, columnspan=3, sticky="w", pady=(6, 0))

        self._progress = ttk.Progressbar(self.root, mode="determinate", length=520)
        self._progress.pack(fill="x", padx=20, pady=(8, 2))
        self._prog_text = tk.StringVar(value="等待任务...")
        ttk.Label(self.root, textvariable=self._prog_text, font=("Microsoft YaHei UI", 9)).pack(anchor="center")

        frame_out = ttk.Frame(self.root)
        frame_out.pack(fill="x", padx=20, pady=(8, 2))
        ttk.Label(frame_out, text=f"保存位置: {DOWNLOAD_DIR}", foreground="#666").pack(side="left")
        ttk.Button(frame_out, text="打开目录", command=self._open_output_dir).pack(side="right")

        frame_log = ttk.LabelFrame(self.root, text="日志", padding=4)
        frame_log.pack(fill="both", expand=True, **pad)
        self._log = tk.Text(
            frame_log, height=6, state="disabled",
            font=("Microsoft YaHei UI", 9), wrap="word",
        )
        scrollbar = ttk.Scrollbar(frame_log, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

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
        lines: list[str] = []
        for label, info, keys in (
            ("抖音", load_cookies(), KEY_COOKIE_NAMES),
            ("B 站", load_bilibili_cookies(), KEY_COOKIE_NAMES_BILI),
        ):
            freshness_label = "缺失"
            if info.status == CookieStatus.MISSING:
                freshness_label = "缺失 ✗"
            else:
                try:
                    plat = "bilibili" if label == "B 站" else "douyin"
                    freshness = probe_cookie_freshness(
                        info.cookie_string, platform=plat,
                    )
                    freshness_label = {
                        CookieStatus.VALID: "有效 ✓",
                        CookieStatus.EXPIRED: "已过期 ✗",
                        CookieStatus.UNKNOWN: "未知",
                    }.get(freshness, "未知")
                except Exception as e:
                    freshness_label = f"未知 ({e})"
            lines.append(f"[{label}] {freshness_label}")
            for name in keys:
                mark = "✓" if name in info.key_cookies else "✗"
                lines.append(f"  {mark}  {name}")
        self._ck_status.set("双平台 Cookie 已加载 — 见下方")
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
            messagebox.showwarning("提示", "请先粘贴链接")
            return

        platform_label = self._platform_var.get()
        platform = "auto" if platform_label == "自动" else (
            "bilibili" if platform_label == "Bilibili" else "douyin"
        )
        quality = int(self._quality_var.get())
        parts_mode = self._parts_var.get()
        prefer_dash = self._dash_var.get()
        use_mux = self._mux_var.get() and self._ffmpeg_available

        self._btn_dl.configure(state="disabled", text="下载中...")
        self._progress.configure(value=0)
        self._prog_text.set("准备下载...")

        thread = threading.Thread(
            target=self._do_download,
            args=(url, platform, quality, parts_mode, prefer_dash, use_mux),
            daemon=True,
        )
        thread.start()

    def _do_download(self, raw_url, platform, quality, parts_mode, prefer_dash, use_mux):
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
        from dydownload.pipeline import download_media, detect_platform

        try:
            if platform == "auto":
                try:
                    platform = detect_platform(raw_url)
                except ValueError as exc:
                    self._dl_fail(str(exc))
                    return
            if platform == "bilibili":
                cookie_info = load_bilibili_cookies()
                ck_missing = (
                    "B 站 Cookie 未就绪，请先登录 B 站后点击插件图标推送"
                )
            else:
                cookie_info = load_cookies()
                ck_missing = "抖音 Cookie 未就绪，请先登录抖音后点击插件图标推送"
            if cookie_info.status == CookieStatus.MISSING:
                self._dl_fail(ck_missing)
                return

            self._log_msg(f"解析作品链接... (平台={platform})")

            def on_event(name, payload):
                if name == "phase":
                    self._log_msg(payload)
                    self._root_call(lambda t=payload: self._prog_text.set(t))
                elif name == "info":
                    mt = payload.get("platform")
                    if mt == "bilibili":
                        self._log_msg(
                            f"作者: @{payload.get('author', '')} | 标题: "
                            f"{(payload.get('title') or '')[:60]}"
                        )
                        self._log_msg(
                            f"分 P: {payload.get('pages', 1)} | "
                            f"{payload.get('width', '?')}x{payload.get('height', '?')}"
                        )
                    elif payload.get("media_type") == "image":
                        self._log_msg(
                            f"检测到图文/图集，共 {payload.get('image_count', 0)} 张图片"
                            + ("（含 BGM）" if payload.get("has_bgm") else "")
                        )
                    else:
                        self._log_msg(
                            f"作者: @{payload.get('author', '')} "
                            f"({payload.get('nickname', '')})"
                        )
                        if payload.get("desc"):
                            self._log_msg(f"描述: {payload['desc'][:60]}")
                elif name == "part":
                    self._log_msg(
                        f"→ 分 P {payload['index']}/{payload['total']}: "
                        f"{payload.get('title', '')}"
                    )
                elif name == "file":
                    fname = payload.get("name", "")
                    if payload.get("status") == "downloading":
                        size = payload.get("size") or 0
                        downloaded = payload.get("downloaded", 0)
                        if size:
                            pct = downloaded / size * 100
                            self._root_call(
                                lambda p=pct: self._progress.configure(value=p)
                            )
                            self._root_call(
                                lambda f=fname, d=downloaded, s=size:
                                self._prog_text.set(
                                    f"下载 {f}: {d/1024:.1f}/{s/1024:.1f} KB"
                                )
                            )
                        else:
                            self._root_call(
                                lambda i=payload.get('index'), t=payload.get('total'),
                                f=fname: self._prog_text.set(
                                    f"下载 {f} ({i}/{t})"
                                )
                            )
                    elif payload.get("status") == "done":
                        self._log_msg(f"  ✓ {fname}")
                    elif payload.get("status") == "error":
                        self._log_msg(f"  ✗ {fname} 失败")
                elif name == "done":
                    self._root_call(lambda: self._progress.configure(value=100))
                    if payload.video:
                        v = payload.video
                        size_mb = v.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"✓ 视频完成: {v.output_path.name} ({size_mb:.1f} MB)"
                        )
                        self._root_call(
                            lambda v=v: self._prog_text.set(
                                f"✓ {v.output_path.name} ({v.size_bytes/1024/1024:.1f} MB)"
                            )
                        )
                    elif payload.image:
                        img = payload.image
                        size_mb = img.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"✓ 图集完成 ({len(img.files)} 文件, {size_mb:.1f} MB)"
                        )
                        self._log_msg(f"  {img.folder}")
                        self._root_call(
                            lambda img=img: self._prog_text.set(
                                f"✓ 图集完成 ({len(img.files)} 文件)"
                            )
                        )
                    elif payload.bilibili:
                        bili = payload.bilibili
                        size_mb = bili.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"✓ B 站完成 ({len(bili.parts)} 文件, {size_mb:.1f} MB)"
                        )
                        for part in bili.parts:
                            self._log_msg(f"  {part.output_path.name}")
                        self._root_call(
                            lambda bili=bili: self._prog_text.set(
                                f"✓ B 站完成 ({len(bili.parts)} 文件)"
                            )
                        )

            try:
                download_media(
                    raw_url,
                    cookie_info.cookie_string,
                    output_dir=DOWNLOAD_DIR,
                    on_event=on_event,
                    platform=platform,
                    qn=quality,
                    prefer_dash=prefer_dash,
                    multi_part_mode=parts_mode,
                    mux=use_mux,
                )
            except BangumiNotSupportedError as e:
                self._dl_fail(f"暂不支持番剧: {e}")
                return
            except BilibiliCookieExpiredError:
                self._dl_fail("B 站 Cookie 已过期，请重新登录并推送")
                return
            except BilibiliNotFoundError as e:
                self._dl_fail(f"B 站作品不可用: {e}")
                return
            except BilibiliAPIError as e:
                self._dl_fail(f"B 站 API 错误: {e}")
                return
            except CookieExpiredError:
                self._dl_fail("Cookie 已过期，请重新登录后推送")
                return
            except VideoNotFoundError as e:
                self._dl_fail(f"作品不可用: {e}")
                return
            except DouyinAPIError as e:
                self._dl_fail(f"抖音 API 错误: {e}")
                return

            self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))
        except Exception as e:
            self._dl_fail(f"{type(e).__name__}: {e}")

    def _dl_fail(self, msg):
        self._log_msg(f"[错误] {msg}")
        self._root_call(lambda: self._prog_text.set(f"✗ {msg}"))
        self._root_call(lambda: self._progress.configure(value=0))
        self._root_call(lambda: self._btn_dl.configure(state="normal", text="下载"))

    def _root_call(self, fn):
        self.root.after(0, fn)

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
