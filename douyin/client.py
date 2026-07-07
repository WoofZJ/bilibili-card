import json
import os
import re
import threading
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse


DETAIL_API_PATH = "/aweme/v1/web/aweme/detail"
USER_PROFILE_API_PATH = "/aweme/v1/web/user/profile/other"
COMMENT_LIST_API_PATH = "/aweme/v1/web/comment/list"

DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_SCROLL_DELAY_MS = 1_200

_thread_state = threading.local()


def fetch_work_info(url: str) -> dict:
    """打开作品页并捕获页面发出的详情接口响应。"""
    aweme_id = extract_aweme_id(url)
    page_url = build_video_page_url(url)

    with _open_page() as page:
        try:
            with page.expect_response(
                lambda response: _is_detail_response(response.url, aweme_id),
                timeout=_timeout_ms(),
            ) as response_info:
                page.goto(page_url, wait_until="domcontentloaded")
            return _response_json(response_info.value, required_key="aweme_detail")
        except _playwright_timeout_error() as exc:
            raise TimeoutError(f"等待抖音详情接口超时: aweme_id={aweme_id}") from exc


def fetch_user_info(user_sec_id: str) -> dict:
    """打开用户主页并捕获用户资料接口响应。"""
    sec_uid = extract_sec_uid(user_sec_id)
    page_url = build_user_page_url(sec_uid)

    with _open_page() as page:
        try:
            with page.expect_response(
                lambda response: _is_user_profile_response(response.url, sec_uid),
                timeout=_timeout_ms(),
            ) as response_info:
                page.goto(page_url, wait_until="domcontentloaded")
            return _response_json(response_info.value, required_key="user")
        except _playwright_timeout_error() as exc:
            raise TimeoutError(f"等待抖音用户资料接口超时: sec_uid={sec_uid}") from exc


def fetch_comments(url: str) -> dict:
    """打开作品页并捕获评论列表接口响应。"""
    aweme_id = extract_aweme_id(url)
    page_url = build_video_page_url(url)

    with _open_page() as page:
        try:
            with page.expect_response(
                lambda response: _is_comment_response(response.url, aweme_id),
                timeout=_timeout_ms(),
            ) as response_info:
                page.goto(page_url, wait_until="domcontentloaded")
                for _ in range(_comment_scroll_rounds()):
                    page.mouse.wheel(0, _env_int("DY_PLAYWRIGHT_SCROLL_PIXELS", 1800))
                    page.wait_for_timeout(_scroll_delay_ms())
            return _response_json(response_info.value, required_key="comments")
        except _playwright_timeout_error() as exc:
            raise TimeoutError(f"等待抖音评论接口超时: aweme_id={aweme_id}") from exc


def extract_aweme_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    for key in ("aweme_id", "modal_id"):
        values = query.get(key)
        if values and values[0]:
            return values[0]

    match = re.search(r"/video/(\d+)", parsed.path)
    if match:
        return match.group(1)

    raise ValueError(f"无法从 URL 中解析作品 ID: {url}")


def extract_sec_uid(user_sec_id: str) -> str:
    if not user_sec_id.startswith(("http://", "https://")):
        return user_sec_id

    parsed = urlparse(user_sec_id)
    query = parse_qs(parsed.query)
    values = query.get("sec_user_id")
    if values and values[0]:
        return values[0]

    sec_uid = parsed.path.rstrip("/").split("/")[-1]
    if sec_uid:
        return sec_uid

    raise ValueError(f"无法从 URL 中解析用户 sec_uid: {user_sec_id}")


def build_video_page_url(url: str) -> str:
    return f"https://www.douyin.com/video/{extract_aweme_id(url)}"


def build_user_page_url(user_sec_id: str) -> str:
    return f"https://www.douyin.com/user/{extract_sec_uid(user_sec_id)}"


@contextmanager
def _open_page():
    if _persistent_browser_enabled():
        context = _persistent_context()
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()
        return

    sync_playwright, _ = _load_playwright()
    playwright = sync_playwright().start()
    browser_name = _browser_name()
    browser = getattr(playwright, browser_name).launch(**_launch_options(browser_name))
    context = _new_context(browser)
    try:
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()
    finally:
        context.close()
        browser.close()
        playwright.stop()


def close_browser() -> None:
    context = getattr(_thread_state, "context", None)
    browser = getattr(_thread_state, "browser", None)
    playwright = getattr(_thread_state, "playwright", None)

    for obj in (context, browser, playwright):
        if obj is None:
            continue
        try:
            if obj is playwright:
                obj.stop()
            else:
                obj.close()
        except Exception:
            pass

    _thread_state.context = None
    _thread_state.browser = None
    _thread_state.playwright = None


def _persistent_context():
    context = getattr(_thread_state, "context", None)
    if context is not None:
        return context

    sync_playwright, _ = _load_playwright()
    playwright = sync_playwright().start()
    browser_name = _browser_name()
    browser = getattr(playwright, browser_name).launch(**_launch_options(browser_name))
    context = _new_context(browser)

    _thread_state.playwright = playwright
    _thread_state.browser = browser
    _thread_state.context = context
    return context


def _new_context(browser):
    context_options = {
        "viewport": {
            "width": _env_int("DY_PLAYWRIGHT_WIDTH", 1707),
            "height": _env_int("DY_PLAYWRIGHT_HEIGHT", 1067),
        },
        "locale": os.getenv("DY_PLAYWRIGHT_LOCALE", "zh-CN"),
        "timezone_id": os.getenv("DY_PLAYWRIGHT_TIMEZONE", "Asia/Shanghai"),
        "user_agent": os.getenv("DY_PLAYWRIGHT_USER_AGENT") or None,
        "extra_http_headers": {
            "Accept-Language": os.getenv(
                "DY_PLAYWRIGHT_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"
            ),
        },
        "service_workers": os.getenv("DY_PLAYWRIGHT_SERVICE_WORKERS", "block"),
    }
    context = browser.new_context(**context_options)
    context.set_default_timeout(_timeout_ms())
    context.set_default_navigation_timeout(_timeout_ms())
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    _block_static_resources(context)
    return context


def _block_static_resources(context) -> None:
    blocked_types = {
        value.strip()
        for value in os.getenv("DY_PLAYWRIGHT_BLOCK_RESOURCES", "").split(",")
        if value.strip()
    }
    if not blocked_types:
        return

    def handle(route):
        if route.request.resource_type in blocked_types:
            route.abort()
        else:
            route.continue_()

    context.route("**/*", handle)


def _load_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少 playwright 依赖，请先安装 requirements.txt 并执行 "
            "`playwright install chromium`，或设置 DY_PLAYWRIGHT_BROWSER=firefox 等配置"
        ) from exc

    return sync_playwright, PlaywrightTimeoutError


def _playwright_timeout_error():
    _, timeout_error = _load_playwright()
    return timeout_error


def _is_detail_response(response_url: str, aweme_id: str) -> bool:
    return _is_api_response(response_url, DETAIL_API_PATH, "aweme_id", aweme_id)


def _is_user_profile_response(response_url: str, sec_uid: str) -> bool:
    return _is_api_response(response_url, USER_PROFILE_API_PATH, "sec_user_id", sec_uid)


def _is_comment_response(response_url: str, aweme_id: str) -> bool:
    return _is_api_response(response_url, COMMENT_LIST_API_PATH, "aweme_id", aweme_id)


def _is_api_response(
    response_url: str,
    api_path: str,
    query_key: str | None = None,
    query_value: str | None = None,
) -> bool:
    parsed = urlparse(response_url)
    if not parsed.netloc.endswith("douyin.com"):
        return False
    if parsed.path.rstrip("/") != api_path:
        return False
    if query_key is None:
        return True

    query = parse_qs(parsed.query)
    return query_value in query.get(query_key, [])


def _response_json(response, required_key: str) -> dict:
    if not response.ok:
        raise RuntimeError(f"抖音接口返回异常: HTTP {response.status} {response.url}")

    try:
        data = response.json()
    except Exception:
        data = json.loads(response.text())

    if not isinstance(data, dict):
        raise RuntimeError("抖音接口响应不是 JSON 对象")
    if required_key not in data:
        raise RuntimeError(f"抖音接口响应缺少 {required_key}: {list(data)[:8]}")
    return data


def _launch_options(browser_name: str) -> dict:
    options = {
        "headless": _env_bool("DY_PLAYWRIGHT_HEADLESS", True),
    }
    if browser_name == "chromium":
        options["args"] = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

    channel = os.getenv("DY_PLAYWRIGHT_CHANNEL")
    if channel and browser_name == "chromium":
        options["channel"] = channel

    executable_path = os.getenv("DY_PLAYWRIGHT_EXECUTABLE_PATH")
    if executable_path:
        options["executable_path"] = executable_path

    slow_mo = os.getenv("DY_PLAYWRIGHT_SLOW_MO")
    if slow_mo:
        options["slow_mo"] = int(slow_mo)

    return options


def _browser_name() -> str:
    browser = os.getenv("DY_PLAYWRIGHT_BROWSER", "chromium").strip().lower()
    if browser not in {"chromium", "firefox", "webkit"}:
        return "chromium"
    return browser


def _persistent_browser_enabled() -> bool:
    return _env_bool("DY_PLAYWRIGHT_PERSISTENT_BROWSER", True)


def _timeout_ms() -> int:
    return _env_int("DY_PLAYWRIGHT_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)


def _scroll_delay_ms() -> int:
    return _env_int("DY_PLAYWRIGHT_SCROLL_DELAY_MS", DEFAULT_SCROLL_DELAY_MS)


def _comment_scroll_rounds() -> int:
    return _env_int("DY_PLAYWRIGHT_COMMENT_SCROLL_ROUNDS", 10)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
