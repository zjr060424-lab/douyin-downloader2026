"""Generate a_bogus signature for Douyin API requests.

Uses py_mini_racer (Python V8 bindings) to run the Douyin signing JS.
The JS code is vendored from the open-source a_bogus reverse-engineering project.
"""

import random
import urllib.parse
from pathlib import Path

from py_mini_racer import MiniRacer

_JS_DIR = Path(__file__).parent / "js"

_COMMON_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "update_version_code": "170400",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "screen_width": "1536",
    "screen_height": "864",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "126.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "126.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "cpu_core_num": "16",
    "device_memory": "8",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "50",
}


def _get_sign_ctx() -> MiniRacer:
    """Lazy-initialise the JS signing context.

    The context is created once and cached on the function so the JS code is
    compiled only once per process lifetime.
    """
    if not hasattr(_get_sign_ctx, "_ctx"):
        js_path = _JS_DIR / "a_bogus.js"
        code = js_path.read_text(encoding="utf-8")
        ctx = MiniRacer()
        ctx.eval(code)
        _get_sign_ctx._ctx = ctx
    return _get_sign_ctx._ctx


def extract_webid(html: str) -> str | None:
    """Extract webid (user_unique_id) from Douyin page RENDER_DATA JSON."""
    import json
    import re
    from urllib.parse import unquote

    match = re.search(
        r'<script id="RENDER_DATA"[^>]*>(.*?)</script>', html
    )
    if not match:
        return None
    try:
        decoded = unquote(match.group(1).strip())
        data = json.loads(decoded)
        return data.get("app", {}).get("odin", {}).get("user_unique_id")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def generate_ms_token(length: int = 120) -> str:
    """Generate a random msToken string like the Douyin frontend does."""
    base = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    return "".join(random.choice(base) for _ in range(length))


def build_params(
    aweme_id: str,
    webid: str = "",
    ms_token: str = "",
    cookie_str: str = "",
) -> dict[str, str]:
    """Build the full parameter dict for an aweme/detail API request."""
    params = dict(_COMMON_PARAMS)
    params["aweme_id"] = aweme_id
    params["msToken"] = ms_token or generate_ms_token()

    if webid:
        params["webid"] = webid

    # Pull screen / device info from cookies if available
    if cookie_str:
        cookies = {}
        for item in cookie_str.replace("; ", ";").split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v

        screen_w = cookies.get("dy_swidth")
        if screen_w:
            params["screen_width"] = screen_w
        screen_h = cookies.get("dy_sheight")
        if screen_h:
            params["screen_height"] = screen_h
        cpu = cookies.get("device_web_cpu_core")
        if cpu:
            params["cpu_core_num"] = cpu
        mem = cookies.get("device_web_memory_size")
        if mem:
            params["device_memory"] = mem
        s_v_web_id = cookies.get("s_v_web_id")
        if s_v_web_id:
            params["verifyFp"] = s_v_web_id
            params["fp"] = s_v_web_id

    return params


def params_to_query(params: dict[str, str]) -> str:
    """Serialize params dict to URL query string (alphabetically sorted)."""
    return "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(params.items())
    )


def generate_a_bogus(query_string: str, user_agent: str) -> str:
    """Generate a_bogus signature for a given query string and user agent.

    The query_string should be the complete, sorted URL query string that
    will be sent to the API endpoint.

    Returns the a_bogus value (including trailing '=').
    """
    ctx = _get_sign_ctx()
    return ctx.call("generate_a_bogus", query_string, user_agent)


def sign_request(
    aweme_id: str,
    user_agent: str,
    webid: str = "",
    ms_token: str = "",
    cookie_str: str = "",
) -> dict[str, str]:
    """Build signed parameters for an aweme/detail API request.

    Returns the complete params dict with a_bogus included, ready to pass
    as query parameters to a GET request.
    """
    params = build_params(
        aweme_id=aweme_id,
        webid=webid,
        ms_token=ms_token,
        cookie_str=cookie_str,
    )
    query = params_to_query(params)
    a_bogus = generate_a_bogus(query, user_agent)
    params["a_bogus"] = a_bogus
    return params
