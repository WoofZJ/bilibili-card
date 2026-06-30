import os
from pathlib import Path

import requests


DEFAULT_API_ENDPOINT = "https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/preview.php?id=1&immgj=0"
REQUEST_FILE = Path(__file__).with_name("request.txt")


def fetch_merchant_info(endpoint: str | None = None) -> dict:
    """获取远行商人接口原始 JSON。"""
    api_endpoint = endpoint or _api_endpoint()
    if not api_endpoint:
        raise RuntimeError("洛克王国远行商人 API 未配置")

    response = requests.get(
        api_endpoint,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=_timeout_seconds(),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("远行商人接口响应不是 JSON 对象")
    return data


def _api_endpoint() -> str:
    env_endpoint = os.getenv("ROCOKINGDOM_MERCHANT_API", "").strip()
    if env_endpoint:
        return env_endpoint

    try:
        file_endpoint = REQUEST_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        file_endpoint = ""
    return file_endpoint or DEFAULT_API_ENDPOINT


def _timeout_seconds() -> int:
    try:
        return int(os.getenv("ROCOKINGDOM_TIMEOUT_SECONDS", "15"))
    except ValueError:
        return 15
