"""Centralized configuration constants."""

from pathlib import Path

# Local cookie server
LOCAL_SERVER_HOST = "127.0.0.1"
LOCAL_SERVER_PORT = 18921
SERVER_PORTS = list(range(18921, 18926))

# Cookie storage
COOKIE_DIR = Path.home() / ".dydownload"
COOKIE_FILE = COOKIE_DIR / "cookies.txt"
NETSCAPE_COOKIE_FILE = COOKIE_DIR / "cookies_netscape.txt"

# Path to yt-dlp executable
YTDLP_PATH = "yt-dlp"  # Look up from PATH first

# Download defaults
DOWNLOAD_DIR = Path.cwd() / "downloads"
CHUNK_SIZE = 1024 * 1024  # 1 MB

# Douyin endpoints
DOUYIN_SHORT_LINK = "https://v.douyin.com/"
DOUYIN_VIDEO_PAGE = "https://www.douyin.com/video/{video_id}"
DOUYIN_AWEME_DETAIL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
IESDOUYIN_ITEM_INFO = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/"
IESDOUYIN_SHARE_PAGE = "https://www.iesdouyin.com/share/video/{video_id}/"

# Key cookies that should be present for a valid session
KEY_COOKIE_NAMES = [
    "ttwid",
    "sessionid",
    "passport_csrf_token",
    "s_v_web_id",
    "odin_tt",
]

# User-agent pool
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
]

# Request headers template (for HTML page fetches)
BASE_HEADERS = {
    "User-Agent": USER_AGENTS[0],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.douyin.com/",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

# Request headers for XHR/API calls (e.g. aweme/detail)
API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA": '"Chromium";v="126", "Google Chrome";v="126"',
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "DNT": "1",
}
