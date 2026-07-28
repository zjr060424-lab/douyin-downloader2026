"""tkinter GUI for dydownload - 抖音 + B 站 双平台下载。"""

import sys
import threading
import time
import traceback as _tb
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path


# ── Diagnostic: install a global excepthook that logs the full traceback to a
# file so we can find where UnicodeEncodeError is raised in the frozen build.
_DBG_LOG = Path.home() / ".dydownload" / "gui_trace.log"


def _excepthook(exc_type, exc_value, exc_tb):
    try:
        _DBG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _DBG_LOG.open("a", encoding="utf-8") as f:
            f.write(
                "=== uncaught {} at {} ===\n".format(
                    exc_type.__name__, time.strftime("%H:%M:%S")
                )
            )
            _tb.print_exception(exc_type, exc_value, exc_tb, file=f)
            f.write("\n")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook

_TRACE_FILE = Path.home() / ".dydownload" / "startup.log"


def _enable_high_dpi() -> None:
    """Ask Windows for native DPI scaling before Tk creates its first window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _system_animations_enabled() -> bool:
    """Honor the Windows client-area animation accessibility preference."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        enabled = ctypes.c_int()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0
        )
        return bool(enabled.value) if ok else True
    except Exception:
        return True


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
    QUALITY_OPTIONS = ("360p", "480p", "720p", "1080p", "1080p+", "1080p60", "4K")
    QUALITY_CODES = {
        "360p": 36,
        "480p": 48,
        "720p": 64,
        "1080p": 80,
        "1080p+": 112,
        "1080p60": 116,
        "4K": 120,
    }
    PART_OPTIONS = ("全部", "仅第一 P")

    COLORS = {
        "canvas": "#DDD8D1",
        "workspace": "#F6F0E9",
        "surface": "#FFFDF9",
        "ink": "#1C1B1A",
        "rail": "#161514",
        "rail_muted": "#817B75",
        "accent": "#EF3154",
        "accent_deep": "#B81838",
        "system": "#F3C846",
        "success": "#28B77D",
        "danger": "#D94242",
        "muted": "#716B65",
        "divider": "#BBB2A9",
        "track": "#D8D0C7",
        "log": "#1D1C1A",
        "log_text": "#D9D6D2",
        "log_muted": "#838B91",
    }

    def __init__(self):
        _enable_high_dpi()
        self.root = tk.Tk()
        self.root.title("dydownload - 抖音 / B 站下载")
        self.root.geometry("1040x800")
        self.root.minsize(940, 760)
        self.root.resizable(True, True)
        self.root.configure(bg=self.COLORS["canvas"])

        self.server = None
        self.server_port = None
        self._download_thread = None
        self._closing = False
        self._ffmpeg_available = bool(find_ffmpeg())
        self._animations_enabled = _system_animations_enabled()
        self._hero_busy = False
        self._hero_stripe_offset = 0
        self._hero_animation_id = None

        self._build_ui()
        self._start_server()
        self._refresh_cookie_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── UI construction ──

    def _build_ui(self):
        c = self.COLORS
        self._configure_styles()

        shell = tk.Frame(self.root, bg=c["canvas"], highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        header = tk.Frame(shell, bg=c["rail"], height=58)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        logo = tk.Label(
            header, text="dy", bg=c["accent"], fg="white",
            font=("Segoe UI", 15, "bold"), padx=8, pady=4,
        )
        logo.pack(side="left", padx=(18, 12), pady=12)
        tk.Label(
            header, text="DYDOWNLOAD // ARENA", bg=c["rail"], fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        tk.Label(
            header, text="LOCAL MEDIA LAUNCHER", bg=c["rail"],
            fg=c["rail_muted"], font=("Cascadia Mono", 9),
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            header, text="1.0.0", bg=c["rail"], fg=c["rail_muted"],
            font=("Cascadia Mono", 9),
        ).pack(side="right", padx=18)

        body = tk.Frame(shell, bg=c["workspace"], highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=78)
        body.grid_columnconfigure(1, weight=1, minsize=560)
        body.grid_columnconfigure(2, minsize=252)

        rail = tk.Frame(body, bg=c["rail"], width=78)
        rail.grid(row=0, column=0, sticky="nsew")
        rail.grid_propagate(False)
        self._make_rail_button(rail, "01", "下载", self._focus_download, True).pack(
            fill="x", pady=(32, 8)
        )
        self._make_rail_button(
            rail, "02", "状态", lambda: self._refresh_cookie_status(False), False
        ).pack(fill="x", pady=8)
        tk.Button(
            rail, text="OUT\n目录", command=self._open_output_dir,
            bg=c["rail"], fg=c["rail_muted"], activebackground=c["rail"],
            activeforeground="white", relief="flat", bd=0,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            highlightthickness=0,
        ).pack(side="bottom", fill="x", pady=24)

        main = tk.Frame(body, bg=c["workspace"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        hero = tk.Frame(main, bg=c["accent"], height=215)
        hero.grid(row=0, column=0, sticky="ew")
        hero.grid_propagate(False)
        self._hero_canvas = tk.Canvas(
            hero, bg=c["accent"], bd=0, highlightthickness=0
        )
        self._hero_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._hero_canvas.bind("<Configure>", self._draw_hero_art)

        hero_content = tk.Frame(hero, bg=c["accent"])
        hero_content.place(x=28, y=17, relwidth=0.80, height=184)
        tk.Label(
            hero_content, text="READY TO PULL", bg=c["accent"],
            fg="#651126", font=("Segoe UI", 9, "bold"),
        ).place(x=0, y=0)
        tk.Label(
            hero_content, text="抓取你的\n下一个作品。", bg=c["accent"],
            fg="white", justify="left", font=("Microsoft YaHei UI", 20, "bold"),
        ).place(x=0, y=26)

        url_row = tk.Frame(hero_content, bg=c["accent"])
        url_row.place(x=0, y=132, relwidth=1.0, height=48)
        url_row.grid_columnconfigure(0, weight=1)
        url_row.grid_rowconfigure(0, weight=1)
        self._url_placeholder = "粘贴抖音或 B 站链接"
        self._url_var = tk.StringVar(value=self._url_placeholder)
        self._url_entry = ttk.Entry(
            url_row, textvariable=self._url_var, style="HeroPlaceholder.TEntry",
            font=("Microsoft YaHei UI", 12),
        )
        self._url_entry.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
        self._url_entry.bind("<Return>", lambda _event: self._start_download())
        self._url_entry.bind("<FocusIn>", self._clear_url_placeholder)
        self._url_entry.bind("<FocusOut>", self._restore_url_placeholder)
        self._btn_dl = ttk.Button(
            url_row, text="启动下载", command=self._start_download,
            style="Hero.TButton", width=11,
        )
        self._btn_dl.grid(row=0, column=1, sticky="ns")

        loadout = tk.Frame(main, bg=c["workspace"], padx=28, pady=10)
        loadout.grid(row=1, column=0, sticky="ew")
        for column in range(3):
            loadout.grid_columnconfigure(column, weight=1, uniform="option")
        tk.Label(
            loadout, text="LOADOUT", bg=c["workspace"], fg=c["muted"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self._platform_var = tk.StringVar(value=self.PLATFORM_OPTIONS[0])
        self._quality_var = tk.StringVar(value="1080p")
        self._parts_var = tk.StringVar(value=self.PART_OPTIONS[0])
        option_specs = (
            ("平台", self._platform_var, self.PLATFORM_OPTIONS),
            ("画质", self._quality_var, self.QUALITY_OPTIONS),
            ("多 P", self._parts_var, self.PART_OPTIONS),
        )
        for column, (label, variable, values) in enumerate(option_specs):
            block = tk.Frame(loadout, bg=c["workspace"])
            block.grid(
                row=1, column=column, sticky="ew",
                padx=(0, 7) if column < 2 else (7, 0),
            )
            tk.Label(
                block, text=label, bg=c["workspace"], fg=c["muted"],
                font=("Microsoft YaHei UI", 10, "bold"),
            ).pack(anchor="w", pady=(0, 5))
            ttk.Combobox(
                block, textvariable=variable, values=values, state="readonly",
                style="Arena.TCombobox", font=("Microsoft YaHei UI", 11),
            ).pack(fill="x", ipady=2)

        toggles = tk.Frame(loadout, bg=c["workspace"])
        toggles.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self._dash_var = tk.BooleanVar(value=True)
        check_options = {
            "bg": c["workspace"],
            "fg": c["ink"],
            "activebackground": c["workspace"],
            "activeforeground": c["ink"],
            "selectcolor": c["accent"],
            "highlightthickness": 0,
            "bd": 0,
            "font": ("Microsoft YaHei UI", 10),
            "cursor": "hand2",
        }
        tk.Checkbutton(
            toggles, text="DASH  优先高清流", variable=self._dash_var,
            **check_options,
        ).pack(side="left")
        self._mux_var = tk.BooleanVar(value=self._ffmpeg_available)
        self._mux_check = tk.Checkbutton(
            toggles, text="MUX  ffmpeg 合流", variable=self._mux_var,
            **check_options,
        )
        self._mux_check.pack(side="left", padx=(24, 0))
        if not self._ffmpeg_available:
            self._mux_check.configure(state="disabled")

        transfer = tk.Frame(main, bg=c["workspace"], padx=28, pady=6)
        transfer.grid(row=2, column=0, sticky="ew")
        transfer.grid_columnconfigure(0, weight=1)
        tk.Label(
            transfer, text="DOWNLOADING", bg=c["workspace"], fg=c["ink"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self._progress_value = tk.StringVar(value="0%")
        tk.Label(
            transfer, textvariable=self._progress_value, bg=c["workspace"],
            fg=c["ink"], font=("Cascadia Mono", 10, "bold"),
        ).grid(row=0, column=1, sticky="e")
        self._progress = ttk.Progressbar(
            transfer, mode="determinate", style="Arena.Horizontal.TProgressbar"
        )
        self._progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 5))
        self._prog_text = tk.StringVar(value="等待任务...")
        tk.Label(
            transfer, textvariable=self._prog_text, bg=c["workspace"],
            fg=c["muted"], font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew")
        ttk.Button(
            transfer, text="打开目录", command=self._open_output_dir,
            style="Outline.TButton",
        ).grid(row=2, column=1, sticky="e")
        tk.Label(
            transfer, text=f"保存到  {DOWNLOAD_DIR}", bg=c["workspace"],
            fg=c["muted"], font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(3, 0))

        log_wrap = tk.Frame(main, bg=c["workspace"], padx=28)
        log_wrap.grid(row=3, column=0, sticky="nsew", pady=(4, 12))
        log_wrap.grid_rowconfigure(1, weight=1)
        log_wrap.grid_columnconfigure(0, weight=1)
        tk.Label(
            log_wrap, text="LIVE FEED", bg=c["workspace"], fg=c["muted"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 7))
        log_frame = tk.Frame(log_wrap, bg=c["log"])
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self._log = tk.Text(
            log_frame, height=5, state="disabled", wrap="word",
            bg=c["log"], fg=c["log_text"], insertbackground="white",
            selectbackground=c["accent_deep"], relief="flat", bd=0,
            padx=14, pady=12, font=("Cascadia Mono", 9),
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        status = tk.Frame(body, bg=c["system"], padx=22, pady=24)
        status.grid(row=0, column=2, sticky="nsew")
        status.grid_columnconfigure(0, weight=1)
        tk.Label(
            status, text="SYSTEM", bg=c["system"], fg="#6A5207",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            status, text="连接与授权", bg=c["system"], fg=c["ink"],
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))
        service_row = tk.Frame(status, bg=c["system"])
        service_row.grid(row=2, column=0, sticky="ew")
        self._service_canvas = tk.Canvas(
            service_row, width=18, height=18, bg=c["system"],
            highlightthickness=0, bd=0,
        )
        self._service_indicator = self._service_canvas.create_oval(
            2, 2, 16, 16, fill=c["muted"], outline=""
        )
        self._service_canvas.pack(side="left")
        self._sv_status = tk.StringVar(value="服务启动中...")
        tk.Label(
            service_row, textvariable=self._sv_status, bg=c["system"],
            fg=c["ink"], font=("Microsoft YaHei UI", 10, "bold"),
            justify="left", wraplength=190,
        ).pack(side="left", padx=(8, 0))

        tk.Frame(status, bg="#6D570F", height=2).grid(
            row=3, column=0, sticky="ew", pady=18
        )
        cookie_header = tk.Frame(status, bg=c["system"])
        cookie_header.grid(row=4, column=0, sticky="ew")
        tk.Label(
            cookie_header, text="COOKIE STATUS", bg=c["system"],
            fg="#6A5207", font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        tk.Button(
            cookie_header, text="刷新", command=lambda: self._refresh_cookie_status(False),
            bg=c["system"], fg=c["ink"], activebackground=c["system"],
            activeforeground=c["accent_deep"], relief="flat", bd=0,
            font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2",
            highlightthickness=0,
        ).pack(side="right")
        self._ck_status = tk.StringVar(value="正在检测凭据...")
        tk.Label(
            status, textvariable=self._ck_status, bg=c["system"], fg=c["ink"],
            font=("Microsoft YaHei UI", 10, "bold"), justify="left",
            wraplength=205,
        ).grid(row=5, column=0, sticky="ew", pady=(10, 4))
        self._ck_details = tk.Text(
            status, height=10, width=24, state="disabled", wrap="none",
            bg=c["system"], fg="#4F430F", relief="flat", bd=0,
            highlightthickness=0, font=("Cascadia Mono", 8),
            selectbackground="#C59F29",
        )
        self._ck_details.grid(row=6, column=0, sticky="nsew")
        status.grid_rowconfigure(6, weight=1)

        ffmpeg_card = tk.Frame(status, bg=c["rail"], padx=14, pady=12)
        ffmpeg_card.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        tk.Label(
            ffmpeg_card,
            text="ffmpeg READY" if self._ffmpeg_available else "ffmpeg OFFLINE",
            bg=c["rail"],
            fg=c["system"] if self._ffmpeg_available else "#F08D8D",
            font=("Cascadia Mono", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            ffmpeg_card,
            text="DASH 音视频将自动合流" if self._ffmpeg_available else "将保留独立音视频文件",
            bg=c["rail"], fg="#F2EEE8", font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(6, 0))

    def _configure_styles(self):
        c = self.COLORS
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Hero.TEntry", fieldbackground=c["surface"], foreground=c["ink"],
            bordercolor=c["ink"], lightcolor=c["ink"], darkcolor=c["ink"],
            insertcolor=c["ink"], padding=8,
        )
        style.map(
            "Hero.TEntry", bordercolor=[("focus", c["system"])],
            lightcolor=[("focus", c["system"])],
            darkcolor=[("focus", c["system"])],
        )
        style.configure(
            "HeroPlaceholder.TEntry", fieldbackground=c["surface"],
            foreground="#7B746E", bordercolor=c["ink"], lightcolor=c["ink"],
            darkcolor=c["ink"], insertcolor=c["ink"], padding=8,
        )
        style.configure(
            "Hero.TButton", background=c["rail"], foreground="white",
            borderwidth=0, padding=(14, 10), font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.map(
            "Hero.TButton",
            background=[("pressed", "#32302E"), ("active", "#292725"), ("disabled", "#786F6B")],
            foreground=[("disabled", "#D6CECA")],
        )
        style.configure(
            "Arena.TCombobox", fieldbackground=c["surface"], background=c["surface"],
            foreground=c["ink"], arrowcolor=c["ink"], bordercolor=c["ink"],
            lightcolor=c["ink"], darkcolor=c["ink"], padding=6,
        )
        style.map(
            "Arena.TCombobox",
            fieldbackground=[("readonly", c["surface"])],
            selectbackground=[("readonly", c["surface"])],
            selectforeground=[("readonly", c["ink"])],
            bordercolor=[("focus", c["accent"])],
        )
        style.configure(
            "Arena.TCheckbutton", background=c["workspace"], foreground=c["ink"],
            font=("Microsoft YaHei UI", 10), padding=5,
            indicatorbackground=c["surface"], indicatorforeground="white",
            indicatorcolor=c["surface"], bordercolor=c["ink"],
        )
        style.map(
            "Arena.TCheckbutton",
            background=[("active", c["workspace"])],
            indicatorbackground=[("selected", c["accent"]), ("disabled", c["track"])],
            indicatorcolor=[("selected", c["accent"])],
            foreground=[("disabled", c["muted"])],
        )
        style.configure(
            "Arena.Horizontal.TProgressbar", background=c["accent"],
            troughcolor=c["track"], bordercolor=c["track"], lightcolor=c["accent"],
            darkcolor=c["accent"], borderwidth=0, thickness=12,
        )
        style.configure(
            "Outline.TButton", background=c["surface"], foreground=c["ink"],
            bordercolor=c["ink"], lightcolor=c["ink"], darkcolor=c["ink"],
            padding=(10, 5), font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map("Outline.TButton", background=[("active", "#E9E2DA")])

    def _make_rail_button(self, parent, index, label, command, active):
        c = self.COLORS
        return tk.Button(
            parent, text=f"{index}\n{label}", command=command,
            bg=c["rail"], fg=c["accent"] if active else c["rail_muted"],
            activebackground=c["rail"], activeforeground="white",
            relief="flat", bd=0, highlightthickness=0, cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"), pady=8,
        )

    def _focus_download(self):
        self._url_entry.focus_set()

    def _clear_url_placeholder(self, _event=None):
        if self._url_var.get() == self._url_placeholder:
            self._url_var.set("")
            self._url_entry.configure(style="Hero.TEntry")

    def _restore_url_placeholder(self, _event=None):
        if not self._url_var.get().strip():
            self._url_var.set(self._url_placeholder)
            self._url_entry.configure(style="HeroPlaceholder.TEntry")

    def _draw_hero_art(self, _event=None):
        if not hasattr(self, "_hero_canvas"):
            return
        canvas = self._hero_canvas
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        canvas.delete("hero-art")
        start = max(width - 250, int(width * 0.58))
        for x in range(start - 80, width + 120, 42):
            offset = self._hero_stripe_offset
            canvas.create_line(
                x + offset, -30, x - 100 + offset, height + 30,
                fill=self.COLORS["accent_deep"], width=10,
                tags="hero-art",
            )
        canvas.create_polygon(
            width - 128, 0, width, 0, width, 86,
            fill=self.COLORS["system"], outline="", tags="hero-art",
        )

    def _set_download_active(self, active):
        self._hero_busy = active
        self._btn_dl.configure(
            state="disabled" if active else "normal",
            text="下载中..." if active else "启动下载",
        )
        if active and self._animations_enabled and self._hero_animation_id is None:
            self._animate_hero_stripes()
        elif not active:
            if self._hero_animation_id is not None:
                try:
                    self.root.after_cancel(self._hero_animation_id)
                except tk.TclError:
                    pass
                self._hero_animation_id = None
            self._hero_stripe_offset = 0
            self._draw_hero_art()

    def _animate_hero_stripes(self):
        if not self._hero_busy or self._closing:
            self._hero_animation_id = None
            return
        self._hero_stripe_offset = (self._hero_stripe_offset + 4) % 42
        self._draw_hero_art()
        self._hero_animation_id = self.root.after(70, self._animate_hero_stripes)

    def _set_progress(self, value):
        value = max(0.0, min(100.0, float(value)))
        self._progress.configure(value=value)
        self._progress_value.set(f"{value:.0f}%")

    def _start_server(self):
        try:
            self.server, self.server_port, _ = start_server()
            self._sv_status.set(f"+ 服务运行中 - 端口 {self.server_port}")
            self._service_canvas.itemconfigure(
                self._service_indicator, fill=self.COLORS["success"]
            )
            self._log_msg(f"Cookie 接收服务已启动 (127.0.0.1:{self.server_port})")
            self._log_msg("浏览器插件可以开始推送 Cookie 了")
        except Exception as e:
            self._sv_status.set(f"X 服务启动失败: {e}")
            self._service_canvas.itemconfigure(
                self._service_indicator, fill=self.COLORS["danger"]
            )
            self._log_msg(f"[错误] 服务启动失败: {e}")

    def _refresh_cookie_status(self, reschedule=True):
        lines: list[str] = []
        for label, info, keys in (
            ("抖音", load_cookies(), KEY_COOKIE_NAMES),
            ("B 站", load_bilibili_cookies(), KEY_COOKIE_NAMES_BILI),
        ):
            freshness_label = "缺失"
            if info.status == CookieStatus.MISSING:
                freshness_label = "缺失 X"
            else:
                try:
                    plat = "bilibili" if label == "B 站" else "douyin"
                    freshness = probe_cookie_freshness(
                        info.cookie_string, platform=plat,
                    )
                    freshness_label = {
                        CookieStatus.VALID: "有效 +",
                        CookieStatus.EXPIRED: "已过期 X",
                        CookieStatus.UNKNOWN: "未知",
                    }.get(freshness, "未知")
                except Exception as e:
                    freshness_label = f"未知 ({e})"
            lines.append(f"[{label}] {freshness_label}")
            for name in keys:
                mark = "+" if name in info.key_cookies else "X"
                lines.append(f"  {mark}  {name}")
        self._ck_status.set("双平台 Cookie 已加载 - 见下方")
        self._update_ck_details("\n".join(lines))
        if reschedule:
            self.root.after(30_000, self._refresh_cookie_status)

    def _update_ck_details(self, text):
        self._ck_details.configure(state="normal")
        self._ck_details.delete("1.0", "end")
        self._ck_details.insert("1.0", text)
        self._ck_details.tag_configure("ok", foreground="#0B6C49")
        self._ck_details.tag_configure("error", foreground="#8F2727")
        for line_number, line in enumerate(text.splitlines(), start=1):
            tag = None
            if " X" in line or "缺失" in line or "过期" in line:
                tag = "error"
            elif " +" in line or "有效" in line:
                tag = "ok"
            if tag:
                self._ck_details.tag_add(
                    tag, f"{line_number}.0", f"{line_number}.end"
                )
        self._ck_details.configure(state="disabled")

    # ── Download ──

    def _start_download(self):
        url = self._url_var.get().strip()
        if url == self._url_placeholder:
            url = ""
        if not url:
            messagebox.showwarning("提示", "请先粘贴链接")
            return

        platform_label = self._platform_var.get()
        platform = "auto" if platform_label == "自动" else (
            "bilibili" if platform_label == "Bilibili" else "douyin"
        )
        quality = self.QUALITY_CODES.get(self._quality_var.get(), 80)
        parts_mode = "all" if self._parts_var.get() == "全部" else "first"
        prefer_dash = self._dash_var.get()
        use_mux = self._mux_var.get() and self._ffmpeg_available

        self._set_download_active(True)
        self._set_progress(0)
        self._prog_text.set("准备下载...")

        thread = threading.Thread(
            target=self._do_download,
            args=(url, platform, quality, parts_mode, prefer_dash, use_mux),
            daemon=True,
        )
        # Surface thread exceptions into the GUI debug log
        def _thread_excepthook(args):
            _excepthook(args.exc_type, args.exc_value, args.exc_traceback)
        thread.excepthook = _thread_excepthook
        self._download_thread = thread
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
            _safe_str,
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
                    self._root_call(lambda t=self._safe_log(payload): self._prog_text.set(t))
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
                                lambda p=pct: self._set_progress(p)
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
                        self._log_msg(f"  + {fname}")
                    elif payload.get("status") == "error":
                        self._log_msg(f"  X {fname} 失败")
                elif name == "done":
                    self._root_call(lambda: self._set_progress(100))
                    if payload.video:
                        v = payload.video
                        size_mb = v.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"+ 视频完成: {v.output_path.name} ({size_mb:.1f} MB)"
                        )
                        self._root_call(
                            lambda v=v: self._prog_text.set(
                                f"+ {v.output_path.name} ({v.size_bytes/1024/1024:.1f} MB)"
                            )
                        )
                    elif payload.image:
                        img = payload.image
                        size_mb = img.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"+ 图集完成 ({len(img.files)} 文件, {size_mb:.1f} MB)"
                        )
                        self._log_msg(f"  {img.folder}")
                        self._root_call(
                            lambda img=img: self._prog_text.set(
                                f"+ 图集完成 ({len(img.files)} 文件)"
                            )
                        )
                    elif payload.bilibili:
                        bili = payload.bilibili
                        size_mb = bili.size_bytes / 1024 / 1024
                        self._log_msg(
                            f"+ B 站完成 ({len(bili.parts)} 文件, {size_mb:.1f} MB)"
                        )
                        for part in bili.parts:
                            self._log_msg(f"  {part.output_path.name}")
                        self._root_call(
                            lambda bili=bili: self._prog_text.set(
                                f"+ B 站完成 ({len(bili.parts)} 文件)"
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

            self._root_call(lambda: self._set_download_active(False))
        except Exception as e:
            # Dump exception object directly — f-string formatting may itself
            # raise UnicodeEncodeError on frozen Windows builds.
            try:
                with _DBG_LOG.open("a", encoding="utf-8") as _f:
                    _f.write(
                        "[{}] caught: type={}, args={!r}\n".format(
                            time.strftime("%H:%M:%S"),
                            type(e).__name__,
                            e.args,
                        )
                    )
                    import traceback as _tb2
                    _tb2.print_exception(type(e), e, e.__traceback__, file=_f)
            except Exception:
                pass
            # Compose a fully-sanitised message: even repr/format on some
            # exception objects can re-trigger UnicodeEncodeError in frozen
            # builds, so we route through _safe_str at every step.
            try:
                msg = "{}: {}".format(
                    type(e).__name__.encode("ascii", errors="replace").decode("ascii"),
                    _safe_str(e),
                )
            except Exception as inner:
                msg = "{}: <formatting failed: {}>".format(
                    type(e).__name__.encode("ascii", errors="replace").decode("ascii"),
                    _safe_str(inner),
                )
            self._dl_fail(msg)

    def _dl_fail(self, msg):
        # Dump raw message to debug log before sanitizing — if a UnicodeEncodeError
        # gets raised further down the pipeline, this lets us see what triggered it.
        try:
            with _DBG_LOG.open("a", encoding="utf-8") as _f:
                _f.write(
                    "[{}] _dl_fail raw: {!r} (type={})\n".format(
                        time.strftime("%H:%M:%S"), msg, type(msg).__name__
                    )
                )
        except Exception:
            pass
        safe = self._safe_log(msg)
        self._log_msg(f"[错误] {safe}")
        self._root_call(lambda: self._prog_text.set(f"X {safe}"))
        self._root_call(lambda: self._set_progress(0))
        self._root_call(lambda: self._set_download_active(False))

    def _root_call(self, fn):
        self.root.after(0, fn)

    def _open_output_dir(self):
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(DOWNLOAD_DIR))

    def _log_msg(self, msg):
        self._root_call(lambda m=self._safe_log(msg): self._append_log(m))

    def _append_log(self, msg):
        self._log.configure(state="normal")
        # Aggressively strip ALL non-ASCII before sending to Tk — the frozen
        # interpreter's Tk has been observed to raise UnicodeEncodeError on
        # any CJK character regardless of the system code page.
        line = "[{}] {}\n".format(time.strftime("%H:%M:%S"), self._safe_log(msg))
        try:
            line.encode("ascii")
        except UnicodeEncodeError:
            line = line.encode("ascii", errors="replace").decode("ascii")
        self._log.insert("end", line)
        self._log.see("end")
        self._log.configure(state="disabled")

    @staticmethod
    def _safe_log(msg: str) -> str:
        # Tk widgets / StringVars on Windows build under PyInstaller have been
        # observed to raise UnicodeEncodeError on any non-ASCII character — even
        # ones that exist in the system code page (cp936 / gbk). The root cause
        # appears to be inside Tk's internal encoding pipeline in the frozen
        # interpreter. Aggressively replace any non-ASCII byte with ``?`` so the
        # GUI text layer always receives pure ASCII.
        if not isinstance(msg, str):
            try:
                msg = str(msg)
            except Exception:
                return "<unprintable>"
        # Strip ALL non-ASCII unconditionally so Tk never sees anything outside
        # the 7-bit range. This sacrifices log readability but guarantees no
        # UnicodeEncodeError can ever escape the GUI layer.
        return msg.encode("ascii", errors="replace").decode("ascii")

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
