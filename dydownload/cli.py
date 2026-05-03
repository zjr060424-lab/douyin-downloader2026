"""CLI commands for dydownload — yt-dlp powered douyin video downloader."""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dydownload.config import (
    COOKIE_FILE,
    NETSCAPE_COOKIE_FILE,
    DOWNLOAD_DIR,
    LOCAL_SERVER_HOST,
    KEY_COOKIE_NAMES,
    YTDLP_PATH,
    USER_AGENTS,
)
from dydownload.cookie_manager import (
    CookieStatus,
    load_cookies,
    probe_cookie_freshness,
)
from dydownload.server import start_server
from dydownload.utils import validate_download_dir

app = typer.Typer(
    name="dydownload",
    help="抖音视频下载工具 — 浏览器插件 + yt-dlp 下载无水印视频",
    add_completion=False,
)

console = Console()


def _find_ytdlp() -> str:
    """Find yt-dlp executable."""
    # Check custom path first
    custom = Path.home() / ".dydownload" / "yt-dlp.exe"
    if custom.exists():
        return str(custom)
    # Check common locations
    for path in [
        r"E:\下载视频\yt-dlp.exe",
        r"E:\下载视频\yt-dlp",
    ]:
        if Path(path).exists():
            return path
    # Check PATH
    found = shutil.which("yt-dlp")
    if found:
        return found
    return "yt-dlp"  # fallback, let subprocess fail with clear error


@app.command()
def download(
    url: str = typer.Argument(..., help="抖音视频链接"),
    output: str = typer.Option("./downloads", help="下载目录"),
    no_server: bool = typer.Option(False, "--no-server", help="不启动 Cookie 接收服务"),
):
    """下载单个抖音视频。

    支持短链接 (v.douyin.com)、完整链接 (douyin.com/video/{id})、
    和分享链接 (iesdouyin.com/share/video/{id})。
    需要浏览器插件提供有效 Cookie。
    """
    console.print()
    console.print(Panel.fit("[bold blue]dydownload v2.0[/bold blue]", border_style="blue"))
    console.print()

    ytdlp = _find_ytdlp()
    if ytdlp == "yt-dlp" and not shutil.which("yt-dlp"):
        console.print("[red][!] 未找到 yt-dlp，请安装或指定路径[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]yt-dlp: {ytdlp}[/dim]")

    # Step 0: Start cookie server
    server = None
    if not no_server:
        server, port, _ = start_server()
        console.print(f"[dim][*] Cookie 接收服务已启动: http://{LOCAL_SERVER_HOST}:{port}[/dim]")

    # Step 1: Ensure we have cookies
    cookie_info = load_cookies()
    if cookie_info.status == CookieStatus.MISSING:
        console.print(
            "[yellow][!] 未检测到 Cookie，请在浏览器中打开抖音确认已登录，"
            "然后点击插件图标推送 Cookie[/yellow]"
        )
        if not no_server:
            console.print("[dim][*] 等待 Cookie 推送... (按 Ctrl+C 取消)[/dim]")
            try:
                while True:
                    time.sleep(2)
                    if COOKIE_FILE.exists():
                        cookie_info = load_cookies()
                        if cookie_info.status != CookieStatus.MISSING:
                            break
            except KeyboardInterrupt:
                console.print("[yellow][!] 用户取消[/yellow]")
                raise typer.Exit(1)
    else:
        console.print(f"[green][✓] Cookie 已就绪 ({len(cookie_info.key_cookies)} 个关键字段)[/green]")

    # Step 2: Download via yt-dlp
    output_dir = validate_download_dir(Path(output))

    # Choose cookie source: prefer Netscape format for yt-dlp
    cookie_arg = None
    if NETSCAPE_COOKIE_FILE.exists():
        cookie_arg = ["--cookies", str(NETSCAPE_COOKIE_FILE)]
    elif COOKIE_FILE.exists():
        cookie_arg = ["--cookies", str(COOKIE_FILE)]

    cmd = [
        ytdlp,
        url,
        "--output", str(output_dir / "%(title).100s-%(id)s.%(ext)s"),
        "--no-playlist",
        "--progress",
        "--newline",
    ]
    if cookie_arg:
        cmd = [ytdlp, url] + cookie_arg + [
            "--output", str(output_dir / "%(title).100s-%(id)s.%(ext)s"),
            "--no-playlist",
            "--progress",
            "--newline",
        ]

    console.print("[dim][*] yt-dlp 开始下载...[/dim]")
    console.print()

    try:
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            console.print()
            console.print("[red][!] 下载失败[/red]")
            console.print(
                "[yellow]提示: 请确保在浏览器中已登录抖音，并且点击了插件图标推送 Cookie[/yellow]"
            )
            raise typer.Exit(1)
    except FileNotFoundError:
        console.print(f"[red][!] 找不到 yt-dlp: {ytdlp}[/red]")
        raise typer.Exit(1)


@app.command()
def status():
    """检查当前 Cookie 状态。"""
    console.print()
    console.print(Panel.fit("[bold blue]Cookie 状态检查[/bold blue]", border_style="blue"))
    console.print()

    cookie_info = load_cookies()

    if cookie_info.status == CookieStatus.MISSING:
        console.print("[red]Cookie 文件不存在或为空[/red]")
        console.print(f"[dim]  路径: {COOKIE_FILE}[/dim]")
        if NETSCAPE_COOKIE_FILE.exists():
            console.print(f"[dim]  Netscape: {NETSCAPE_COOKIE_FILE} (存在)[/dim]")
        else:
            console.print(f"[dim]  Netscape: {NETSCAPE_COOKIE_FILE} (不存在)[/dim]")
        console.print()
        console.print("[yellow]请在浏览器中打开抖音，然后点击插件图标推送 Cookie[/yellow]")
        return

    # Display key cookie table
    table = Table(title="关键 Cookie 字段")
    table.add_column("Cookie", style="cyan")
    table.add_column("状态", style="green")
    table.add_column("值预览", style="dim")

    for name in KEY_COOKIE_NAMES:
        if name in cookie_info.key_cookies:
            val = cookie_info.key_cookies[name]
            preview = val[:30] + "..." if len(val) > 30 else val
            table.add_row(name, "✓", preview)
        else:
            table.add_row(name, "[red]✗ 缺失[/red]", "-")

    console.print(table)
    console.print()

    # Check which cookie files exist
    console.print(f"[dim]Cookie 文件: {COOKIE_FILE} {'[green]存在[/green]' if COOKIE_FILE.exists() else '[red]不存在[/red]'}[/dim]")
    if NETSCAPE_COOKIE_FILE.exists():
        console.print(f"[dim]Netscape:    {NETSCAPE_COOKIE_FILE} [green]存在[/green] ({NETSCAPE_COOKIE_FILE.stat().st_size} bytes)[/dim]")

    # Probe freshness
    freshness = probe_cookie_freshness(cookie_info.cookie_string)
    if freshness == CookieStatus.VALID:
        console.print("[green]Cookie 状态: 有效 ✓[/green]")
    elif freshness == CookieStatus.EXPIRED:
        console.print("[red]Cookie 状态: 已过期 ✗[/red]")
        console.print("[yellow]请在浏览器中打开抖音刷新后重新推送 Cookie[/yellow]")
    else:
        console.print("[yellow]Cookie 状态: 无法验证（可能网络问题）[/yellow]")

    # yt-dlp check
    ytdlp = _find_ytdlp()
    if Path(ytdlp).exists() or shutil.which(ytdlp):
        console.print(f"[green]yt-dlp:    {ytdlp} ✓[/green]")
    else:
        console.print(f"[red]yt-dlp:    未找到 ✗[/red]")


@app.command()
def test(
    url: str = typer.Argument(..., help="抖音视频链接 (douyin.com/video/{id})"),
):
    """测试 a_bogus 签名是否正常工作并获取视频信息。

    适合调试用。提供一个抖音视频 URL，会依次执行：
    1. 获取视频页面 → 提取 WebID
    2. 生成 a_bogus 签名
    3. 调用 aweme/detail API 获取视频数据
    4. 显示无水印视频 URL、作者、分辨率等信息
    """
    import random

    from dydownload.api_client import (
        fetch_video_page,
        fetch_aweme_detail,
        DouyinAPIError,
        CookieExpiredError,
        VideoNotFoundError,
    )
    from dydownload.signature import extract_webid
    from dydownload.video_parser import parse_from_aweme_detail

    console.print()
    console.print(Panel.fit("[bold blue]a_bogus 签名测试[/bold blue]", border_style="blue"))
    console.print()

    # ── Load cookies ──
    cookie_info = load_cookies()
    if cookie_info.status == CookieStatus.MISSING:
        console.print(
            "[red][!] 未找到 Cookie[/red]\n"
            "[yellow]请在浏览器中登录抖音后点插件图标推送 Cookie[/yellow]"
        )
        raise typer.Exit(1)

    cookie_str = cookie_info.cookie_string
    freshness = probe_cookie_freshness(cookie_str)
    console.print(f"[dim]Cookie 状态: {freshness}[/dim]")

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
        console.print("[red][!] 无法从 URL 中提取视频 ID[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Video ID: {video_id}[/dim]")

    ua = random.choice(USER_AGENTS)

    # ── Step 1: Fetch video page ──
    console.print("\n[bold]Step 1:[/bold] 获取视频页面...")
    try:
        html = fetch_video_page(video_id, cookie_str, debug=False)
        console.print(f"  [green]✓[/green] 页面获取成功 ({len(html):,} chars)")
    except CookieExpiredError:
        console.print("[red][!] Cookie 已过期，请重新推送[/red]")
        raise typer.Exit(1)
    except DouyinAPIError as e:
        console.print(f"[red][!] {e}[/red]")
        raise typer.Exit(1)

    webid = extract_webid(html)
    if not webid:
        m2 = re.search(r'"user_unique_id"\s*:\s*"(\d+)"', html)
        if m2:
            webid = m2.group(1)
    console.print(f"  [dim]WebID: {webid or '未找到'}[/dim]")

    # ── Step 2: Call aweme/detail with a_bogus ──
    console.print("\n[bold]Step 2:[/bold] 调用 aweme/detail API (带 a_bogus 签名)...")
    try:
        data = fetch_aweme_detail(
            video_id,
            cookie_string=cookie_str,
            webid=webid or "",
            user_agent=ua,
        )
        console.print("  [green]✓[/green] API 调用成功 (status_code: 0)")

    except VideoNotFoundError as e:
        console.print(f"  [yellow][!] 视频不可用: {e}[/yellow]")
        console.print(
            "  这意味着 a_bogus 签名 [green]正确[/green]，但该视频可能不存在或已删除。\n"
            "  请换一个当前可播放的视频链接再试。"
        )
        raise typer.Exit(1)
    except DouyinAPIError as e:
        console.print(f"  [red][!] API 错误: {e}[/red]")
        raise typer.Exit(1)

    # ── Step 3: Parse video info ──
    console.print("\n[bold]Step 3:[/bold] 解析视频数据...")
    vinfo = parse_from_aweme_detail(data)
    if not vinfo:
        # Try direct extraction
        aweme_detail = data.get("aweme_detail", {})
        if not aweme_detail:
            console.print("  [red][!] 响应中没有视频数据[/red]")
            raise typer.Exit(1)
        else:
            from dydownload.video_parser import _extract_video_info
            vinfo = _extract_video_info(aweme_detail)

    if vinfo:
        console.print("  [green]✓[/green] 视频数据解析成功")
        console.print()
        table = Table(title="视频信息", show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        if vinfo.desc:
            table.add_row("描述", vinfo.desc[:120])
        table.add_row("作者", f"@{vinfo.author_unique_id} ({vinfo.author_nickname})")
        table.add_row("分辨率", f"{vinfo.width}x{vinfo.height}")
        table.add_row("时长", f"{vinfo.duration_ms / 1000:.1f}s")
        table.add_row("发布时间", str(vinfo.create_time))
        if vinfo.no_watermark_url:
            table.add_row("无水印 URL", vinfo.no_watermark_url[:120])
        if vinfo.watermark_url:
            table.add_row("有水印 URL", vinfo.watermark_url[:120])
        if vinfo.music_url:
            table.add_row("音频 URL", vinfo.music_url[:120])
        console.print(table)
        console.print()
        console.print("[green bold]✓ a_bogus 签名验证通过！[/green bold]")
        console.print(
            "[dim]提示: yt-dlp 目前无法下载抖音视频（同样受 a_bogus 限制），请用上述无水印 URL 手动下载。[/dim]"
        )
    else:
        console.print("  [red][!] 无法解析视频数据[/red]")
        raise typer.Exit(1)


@app.command()
def download(
    url: str = typer.Argument(..., help="抖音视频链接"),
    output: str = typer.Option("./downloads", help="下载目录"),
    no_watermark: bool = typer.Option(True, help="下载无水印版本（默认开启）"),
):
    """直接下载抖音视频（无需 yt-dlp）。

    支持短链接 (v.douyin.com)、完整链接 (douyin.com/video/{id})、
    和分享链接 (iesdouyin.com/share/video/{id})。
    使用自研 a_bogus 签名直接调用抖音 API，绕过 yt-dlp 限制。
    """
    import random
    import re

    import httpx

    from dydownload.api_client import (
        fetch_video_page,
        fetch_aweme_detail,
        DouyinAPIError,
        CookieExpiredError,
        VideoNotFoundError,
    )
    from dydownload.signature import extract_webid
    from dydownload.video_parser import parse_from_aweme_detail
    from dydownload.downloader import download_video

    console.print()
    console.print(Panel.fit("[bold blue]dydownload — 抖音无水印视频下载[/bold blue]", border_style="blue"))
    console.print()

    # ── Load cookies ──
    cookie_info = load_cookies()
    if cookie_info.status == CookieStatus.MISSING:
        console.print("[red][!] 未找到 Cookie[/red]")
        console.print("[yellow]请在浏览器中登录抖音后点插件图标推送 Cookie[/yellow]")
        raise typer.Exit(1)

    cookie_str = cookie_info.cookie_string
    freshness = probe_cookie_freshness(cookie_str)
    console.print(f"[dim]Cookie 状态: {freshness}[/dim]")

    # ── Resolve short link ──
    if "v.douyin.com" in url:
        console.print(f"[dim]解析短链接: {url}[/dim]")
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                resp = client.get(url)
                if resp.status_code in (301, 302):
                    url = resp.headers.get("Location", url)
                    console.print(f"[dim] → {url[:80]}...[/dim]")
        except Exception as e:
            console.print(f"[red][!] 短链接解析失败: {e}[/red]")
            raise typer.Exit(1)

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
        console.print("[red][!] 无法从 URL 中提取视频 ID[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Video ID: {video_id}[/dim]")

    ua = random.choice(USER_AGENTS)

    # ── Step 1: Fetch video page ──
    console.print("[dim][*] 获取视频页面...[/dim]")
    try:
        html = fetch_video_page(video_id, cookie_str, debug=False)
    except CookieExpiredError:
        console.print("[red][!] Cookie 已过期，请重新推送[/red]")
        raise typer.Exit(1)
    except DouyinAPIError as e:
        console.print(f"[red][!] {e}[/red]")
        raise typer.Exit(1)

    webid = extract_webid(html)
    if not webid:
        m2 = re.search(r'"user_unique_id"\s*:\s*"(\d+)"', html)
        if m2:
            webid = m2.group(1)

    # ── Step 2: Call API with a_bogus ──
    console.print("[dim][*] 获取视频信息 (a_bogus 签名)...[/dim]")
    try:
        data = fetch_aweme_detail(video_id, cookie_string=cookie_str, webid=webid or "", user_agent=ua)
    except VideoNotFoundError as e:
        console.print(f"[red][!] 视频不可用: {e}[/red]")
        raise typer.Exit(1)
    except DouyinAPIError as e:
        console.print(f"[red][!] API 错误: {e}[/red]")
        raise typer.Exit(1)

    vinfo = parse_from_aweme_detail(data)
    if not vinfo:
        console.print("[red][!] 无法解析视频数据[/red]")
        raise typer.Exit(1)

    # ── Step 3: Download ──
    media_url = vinfo.no_watermark_url if no_watermark else (vinfo.watermark_url or vinfo.no_watermark_url)
    if not media_url:
        console.print("[red][!] 没有可下载的视频 URL[/red]")
        raise typer.Exit(1)

    url_type = "无水印" if no_watermark else "有水印"
    console.print(f"[green]✓ 获取{url_type}地址成功[/green]")
    console.print(f"[dim]作者: @{vinfo.author_unique_id}[/dim]")
    console.print(f"[dim]描述: {vinfo.desc[:80] if vinfo.desc else '(无)'}[/dim]")
    console.print(f"[dim]分辨率: {vinfo.width}x{vinfo.height}, 时长: {vinfo.duration_ms/1000:.1f}s[/dim]")

    # Build filename
    safe_title = re.sub(r'[\x00-\x1f\\/*?:"<>|]', '', vinfo.desc[:80] if vinfo.desc else "douyin").strip()
    ext = ".mp4"
    filename = f"{safe_title}-{vinfo.video_id}{ext}"

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    console.print()
    console.print(f"[bold]下载:[/bold] {filename}")
    try:
        download_headers = {
            "Referer": f"https://www.douyin.com/video/{video_id}/",
            "User-Agent": ua,
        }
        download_video(media_url, output_path, headers=download_headers)
    except Exception as e:
        console.print(f"[red][!] 下载失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def serve(
    port: int = typer.Option(18921, help="监听端口"),
):
    """启动 Cookie 接收服务（前台运行）。"""
    console.print()
    console.print(Panel.fit("[bold blue]Cookie 接收服务[/bold blue]", border_style="blue"))
    console.print()

    server, actual_port, _ = start_server(port=port)

    console.print(f"[green]服务已启动: http://{LOCAL_SERVER_HOST}:{actual_port}[/green]")
    console.print(f"[dim]接收端点: POST http://{LOCAL_SERVER_HOST}:{actual_port}/cookie[/dim]")
    console.print(f"[dim]健康检查: GET  http://{LOCAL_SERVER_HOST}:{actual_port}/health[/dim]")
    console.print()
    console.print("[yellow]按 Ctrl+C 停止服务[/yellow]")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print()
        console.print("[dim]服务已停止[/dim]")
        server.shutdown()


def main():
    """Entry point for console_scripts."""
    app()


if __name__ == "__main__":
    app()
