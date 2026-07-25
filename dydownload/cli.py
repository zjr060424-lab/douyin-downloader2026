"""CLI commands for dydownload — a_bogus-signed douyin media downloader."""

import re
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dydownload.config import (
    COOKIE_FILE,
    NETSCAPE_COOKIE_FILE,
    KEY_COOKIE_NAMES,
    LOCAL_SERVER_HOST,
    USER_AGENTS,
)
from dydownload.cookie_manager import (
    CookieStatus,
    load_cookies,
    probe_cookie_freshness,
)
from dydownload.server import start_server

app = typer.Typer(
    name="dydownload",
    help="抖音视频/图集下载工具 — 浏览器插件推送 Cookie + a_bogus 签名下载",
    add_completion=False,
)

console = Console()


def _extract_url(text: str) -> str:
    """Extract a supported platform URL from share text."""
    from dydownload.pipeline import extract_url
    return extract_url(text)


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
    3. 调用 aweme/detail API 获取作品数据
    4. 显示无水印视频 URL 或图集图片列表、作者、分辨率等信息
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
    from dydownload.pipeline import extract_url, resolve_short_link, extract_aweme_id

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

    url = extract_url(url)
    url = resolve_short_link(url)
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        console.print("[red][!] 无法从 URL 中提取作品 ID[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Aweme ID: {aweme_id}[/dim]")

    ua = random.choice(USER_AGENTS)

    # ── Step 1: Fetch page ──
    console.print("\n[bold]Step 1:[/bold] 获取作品页面...")
    try:
        html = fetch_video_page(aweme_id, cookie_str, debug=False)
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
            aweme_id,
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
    console.print("\n[bold]Step 3:[/bold] 解析作品数据...")
    vinfo = parse_from_aweme_detail(data)
    if not vinfo:
        console.print("  [red][!] 无法解析视频数据[/red]")
        raise typer.Exit(1)

    console.print(f"  [green]✓[/green] 解析成功 [dim](media_type={vinfo.media_type})[/dim]")
    console.print()
    table = Table(title="作品信息", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    if vinfo.desc:
        table.add_row("描述", vinfo.desc[:120])
    table.add_row("作者", f"@{vinfo.author_unique_id} ({vinfo.author_nickname})")
    table.add_row("类型", "图文/图集" if vinfo.is_image else "视频")
    if not vinfo.is_image:
        table.add_row("分辨率", f"{vinfo.width}x{vinfo.height}")
        table.add_row("时长", f"{vinfo.duration_ms / 1000:.1f}s")
        if vinfo.no_watermark_url:
            table.add_row("无水印 URL", vinfo.no_watermark_url[:120])
        if vinfo.watermark_url:
            table.add_row("有水印 URL", vinfo.watermark_url[:120])
    else:
        table.add_row("图片数", str(len(vinfo.images)))
        live_count = sum(1 for u in vinfo.image_live_urls if u)
        if live_count:
            table.add_row("实况图", f"{live_count} 张")
        for i, url in enumerate(vinfo.images[:3], start=1):
            table.add_row(f"图片 {i}", url[:120])
        if len(vinfo.images) > 3:
            table.add_row("…", f"还有 {len(vinfo.images) - 3} 张")
    if vinfo.music_url:
        table.add_row("背景音乐 URL", vinfo.music_url[:120])
    table.add_row("发布时间", str(vinfo.create_time))
    console.print(table)
    console.print()
    console.print("[green bold]✓ a_bogus 签名验证通过！[/green bold]")
    console.print(
        "[dim]提示: 运行 [cyan]python -m dydownload download <url>[/cyan] 直接下载此作品。[/dim]"
    )


@app.command()
def download(
    url: str = typer.Argument(..., help="抖音视频/图集 或 B 站视频链接"),
    output: str = typer.Option("./downloads", help="下载目录"),
    no_watermark: bool = typer.Option(True, help="下载无水印版本（默认开启，抖音用）"),
    platform: str = typer.Option(
        "auto", "--platform", help="平台: auto / douyin / bilibili",
    ),
    quality: int = typer.Option(
        80, "--quality", help="B 站画质 (qn): 80=1080p, 112=1080p+, 116=1080p60, 120=4K",
    ),
    prefer_dash: bool = typer.Option(
        True, "--prefer-dash/--no-dash", help="B 站优先 DASH 流（默认开）",
    ),
    parts: str = typer.Option(
        "all", "--parts", help="B 站多 P 处理: all / first",
    ),
    mux: bool = typer.Option(
        True, "--mux/--no-mux", help="B 站 DASH 下载后用 ffmpeg 自动合流",
    ),
):
    """下载抖音视频/图集 或 B 站普通视频。

    抖音：短链接、完整视频链接、图文/图集、分享链接，自动 a_bogus 签名。
    B 站：bilibili.com/video/BV... 或 b23.tv 短链接；自动 WBI 签名。
    番剧(bangumi)暂不支持。
    """
    from dydownload.pipeline import (
        BangumiNotSupportedError,
        BilibiliCookieExpiredError,
        CookieExpiredError as PipelineCookieExpiredError,
        DouyinAPIError as PipelineDouyinAPIError,
        VideoNotFoundError as PipelineVideoNotFoundError,
        detect_platform,
        download_media,
    )

    console.print()
    console.print(Panel.fit("[bold blue]dydownload — 多平台下载[/bold blue]", border_style="blue"))
    console.print()

    # ── Platform auto-detect (only used for informative messages; download_media
    #    resolves the platform itself when ``platform=="auto"``)
    if platform == "auto":
        try:
            platform = detect_platform(url)
        except ValueError as e:
            console.print(f"[red][!] {e}[/red]")
            raise typer.Exit(1)
        console.print(f"[dim]自动识别平台: {platform}[/dim]")
    platform = platform.lower()

    # ── Load cookies (per platform) ──
    if platform == "bilibili":
        from dydownload.cookie_manager import (
            load_bilibili_cookies,
            probe_cookie_freshness as _probe_fresh,
        )
        cookie_info = load_bilibili_cookies()
        ck_missing_hint = "请在浏览器中登录 B 站后点插件图标推送 Cookie (SESSDATA/bili_jct/buvid3)"
    else:
        from dydownload.cookie_manager import probe_cookie_freshness as _probe_fresh
        cookie_info = load_cookies()
        ck_missing_hint = "请在浏览器中登录抖音后点插件图标推送 Cookie"

    if cookie_info.status == CookieStatus.MISSING:
        console.print(f"[red][!] 未找到 {platform} 的 Cookie[/red]")
        console.print(f"[yellow]{ck_missing_hint}[/yellow]")
        raise typer.Exit(1)

    cookie_str = cookie_info.cookie_string
    try:
        freshness = _probe_fresh(cookie_str, platform=platform)
    except TypeError:
        # Backwards compat — older probe signature
        freshness = _probe_fresh(cookie_str)
    console.print(f"[dim]Cookie 状态: {freshness}[/dim]")

    # ── Run the shared pipeline ──
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    def on_event(name, payload):
        if name == "phase":
            console.print(f"[dim][*] {payload}[/dim]")
        elif name == "info":
            mt = payload.get("media_type")
            if mt == "image":
                console.print(
                    f"[green]✓ 检测到图文/图集[/green] "
                    f"[dim]({payload['image_count']} 张图片, "
                    f"BGM: {'有' if payload['has_bgm'] else '无'})[/dim]"
                )
            elif payload.get("platform") == "bilibili":
                console.print(
                    f"[green]✓ B 站视频[/green] "
                    f"[dim]({payload.get('pages', 1)} P, "
                    f"{payload.get('width', '?')}x{payload.get('height', '?')}, "
                    f"~{payload.get('duration', 0)}s)[/dim]"
                )
                console.print(f"[dim]作者: @{payload['author']}[/dim]")
                console.print(f"[dim]标题: {payload['title'][:80]}[/dim]")
            else:
                console.print(f"[dim]作者: @{payload.get('author', '')} ({payload.get('nickname', '')})[/dim]")
                if payload.get("desc"):
                    console.print(f"[dim]描述: {payload['desc'][:80]}[/dim]")
        elif name == "part":
            console.print(
                f"[bold]→ 分 P {payload['index']}/{payload['total']}: "
                f"{payload.get('title', '')}[/bold]"
            )
        elif name == "file":
            status = payload["status"]
            name_ = payload["name"]
            if status == "downloading":
                if payload.get("size"):
                    console.print(f"[dim]  → {name_} (开始下载...)[/dim]")
                else:
                    console.print(f"[dim]  → {name_} ({payload['index']}/{payload['total']})[/dim]")
            elif status == "done":
                size_kb = (payload.get("size") or payload.get("downloaded") or 0) / 1024
                console.print(f"[green]  ✓ {name_}[/green] [dim]({size_kb:.1f} KB)[/dim]")
            elif status == "error":
                console.print(f"[yellow]  [!] {name_} 失败[/yellow]")
        elif name == "done":
            if payload.video:
                v = payload.video
                size_mb = v.size_bytes / 1024 / 1024
                console.print()
                console.print(f"[bold green]✓ 视频下载完成[/bold green] [dim]({size_mb:.1f} MB)[/dim]")
                console.print(f"[dim]{v.output_path}[/dim]")
            elif payload.image:
                img = payload.image
                console.print()
                console.print(
                    f"[bold green]✓ 图集下载完成[/bold green] "
                    f"[dim]({len(img.files)} 个文件, "
                    f"{img.size_bytes / 1024 / 1024:.1f} MB)[/dim]"
                )
                console.print(f"[dim]{img.folder}[/dim]")
            elif payload.bilibili:
                bili = payload.bilibili
                size_mb = bili.size_bytes / 1024 / 1024
                console.print()
                console.print(
                    f"[bold green]✓ B 站下载完成[/bold green] "
                    f"[dim]({len(bili.parts)} 个文件, {size_mb:.1f} MB)[/dim]"
                )
                for part in bili.parts:
                    console.print(f"[dim]  {part.output_path.name}[/dim]")

    try:
        download_media(
            url,
            cookie_str,
            output_dir=output_dir,
            on_event=on_event,
            platform=platform,
            qn=quality,
            prefer_dash=prefer_dash,
            multi_part_mode=parts,
            mux=mux,
        )
    except BangumiNotSupportedError as e:
        console.print(f"[red][!] {e}[/red]")
        raise typer.Exit(1)
    except BilibiliCookieExpiredError:
        console.print("[red][!] B 站 Cookie 过期或不完整，请重新登录并推送 SESSDATA[/red]")
        raise typer.Exit(1)
    except PipelineCookieExpiredError:
        console.print("[red][!] Cookie 已过期，请重新推送[/red]")
        raise typer.Exit(1)
    except PipelineVideoNotFoundError as e:
        console.print(f"[red][!] 作品不可用: {e}[/red]")
        raise typer.Exit(1)
    except PipelineDouyinAPIError as e:
        console.print(f"[red][!] {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red][!] 下载失败: {type(e).__name__}: {e}[/red]")
        raise typer.Exit(1)

    # `no_watermark` is preserved for the legacy video flow (always honoured by
    # the shared pipeline for video posts); kept as a flag for compatibility.
    _ = no_watermark


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
