from __future__ import annotations

import json
import urllib.parse
from hashlib import md5
from pathlib import Path
from random import randrange
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests


VALID_QUALITY_LEVELS = {
    "standard",
    "exhigh",
    "lossless",
    "hires",
    "sky",
    "jyeffect",
    "jymaster",
    "dolby",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 "
    "NeteaseMusicDesktop/2.10.2.200154"
)
REFERER = "https://music.163.com/"

SONG_URL_V1 = "https://interface3.music.163.com/eapi/song/enhance/player/url/v1"
SONG_DETAIL_V3 = "https://interface3.music.163.com/api/v3/song/detail"
LYRIC_API = "https://interface3.music.163.com/api/song/lyric"

_AES_KEY = b"e82ckenh8dichen8"
_DEFAULT_CONFIG = {
    "os": "pc",
    "appver": "",
    "osver": "",
    "deviceId": "pyncm!",
}
_DEFAULT_COOKIES = {
    "os": "pc",
    "appver": "",
    "osver": "",
    "deviceId": "pyncm!",
}

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_ID_RE = re.compile(r"^\d+$")
_ID_IN_TEXT_RE = re.compile(r"(?:song\?id=|[?&]id=|song/)(\d+)")


class NeteaseClientError(RuntimeError):
    """网易云外部请求失败。"""


def fetch_song_detail(song_id: int) -> dict:
    """获取歌曲详情原始 JSON。"""
    data = {"c": json.dumps([{"id": song_id, "v": 0}])}
    result = _post_json(SONG_DETAIL_V3, data=data)
    if result.get("code") != 200:
        raise NeteaseClientError(f"获取歌曲详情失败: {result.get('message', '未知错误')}")
    return result


def fetch_song_url(song_id: int, quality: str = "lossless") -> dict:
    """获取歌曲播放/下载链接原始 JSON。"""
    config = _DEFAULT_CONFIG.copy()
    config["requestId"] = str(randrange(20_000_000, 30_000_000))

    payload: dict[str, Any] = {
        "ids": [song_id],
        "level": quality,
        "encodeType": "mp4" if quality == "dolby" else "flac",
        "header": json.dumps(config),
    }
    if quality == "sky":
        payload["immerseType"] = "c51"

    params = _encrypt_params(SONG_URL_V1, payload)
    result = _post_json(
        SONG_URL_V1,
        data={"params": params},
        cookies=_load_cookies(),
    )
    if result.get("code") != 200:
        raise NeteaseClientError(f"获取歌曲URL失败: {result.get('message', '未知错误')}")
    return result


def fetch_lyric(song_id: int) -> dict:
    """获取歌曲歌词原始 JSON。"""
    data = {
        "id": song_id,
        "cp": "false",
        "tv": "0",
        "lv": "0",
        "rv": "0",
        "kv": "0",
        "yv": "0",
        "ytv": "0",
        "yrv": "0",
    }
    result = _post_json(LYRIC_API, data=data, cookies=_load_cookies())
    if result.get("code") != 200:
        raise NeteaseClientError(f"获取歌词失败: {result.get('message', '未知错误')}")
    return result


def extract_song_id(value: str) -> int:
    """从歌曲 ID、网易云歌曲 URL 或分享文本中提取歌曲 ID。"""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("必须提供歌曲ID或网易云歌曲链接")

    if _ID_RE.fullmatch(raw):
        return int(raw)

    url = _pick_url(raw).strip()
    url = resolve_short_url(url)
    parsed = urlparse(url)

    for query in (parsed.query, _fragment_query(parsed.fragment)):
        values = parse_qs(query).get("id")
        if values and values[0].isdigit():
            return int(values[0])

    match = _ID_IN_TEXT_RE.search(url)
    if match:
        return int(match.group(1))

    raise ValueError(f"无法从输入中解析网易云歌曲ID: {value}")


def resolve_short_url(url: str) -> str:
    """将 163cn.tv 短链接解析为完整网易云 URL。"""
    if "163cn.tv" not in url:
        return url

    try:
        response = requests.get(url, allow_redirects=False, timeout=10)
        location = response.headers.get("Location")
        if location:
            return urljoin(url, location)

        response = requests.get(url, allow_redirects=True, timeout=10)
        return response.url
    except requests.RequestException as exc:
        raise NeteaseClientError(f"解析网易云短链接失败: {exc}") from exc


def _post_json(
    url: str,
    data: dict[str, Any],
    cookies: dict[str, str] | None = None,
) -> dict:
    request_cookies = _DEFAULT_COOKIES.copy()
    request_cookies.update(cookies or {})

    try:
        response = requests.post(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": REFERER,
            },
            cookies=request_cookies,
            data=data,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise NeteaseClientError(f"HTTP请求失败: {exc}") from exc
    except ValueError as exc:
        raise NeteaseClientError(f"解析响应数据失败: {exc}") from exc

    if not isinstance(result, dict):
        raise NeteaseClientError("网易云接口响应不是 JSON 对象")
    return result


def _load_cookies() -> dict[str, str]:
    with open(".env", "r", encoding="utf-8") as f:
        content = f.read()
        for line in content.splitlines():
            if line.startswith("NETEASE_CLOUD_COOKIE="):
                cookie_value = line.split("=", 1)[1].strip().strip("'\"")
                return _parse_cookie_string(cookie_value)


def _parse_cookie_string(cookie_string: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not cookie_string:
        return cookies

    for sep in (";", "\n"):
        if sep in cookie_string:
            pairs = cookie_string.split(sep)
            break
    else:
        pairs = [cookie_string]

    for pair in pairs:
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            cookies[key] = value
    return cookies


def _encrypt_params(url: str, payload: dict[str, Any]) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    url_path = urllib.parse.urlparse(url).path.replace("/eapi/", "/api/")
    payload_json = json.dumps(payload)
    digest = _hash_hex_digest(f"nobody{url_path}use{payload_json}md5forencrypt")
    params = f"{url_path}-36cd479b6b5-{payload_json}-36cd479b6b5-{digest}"

    padder = padding.PKCS7(algorithms.AES(_AES_KEY).block_size).padder()
    padded_data = padder.update(params.encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(_AES_KEY), modes.ECB())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded_data) + encryptor.finalize()

    return _hex_digest(encrypted)


def _hash_hex_digest(text: str) -> str:
    return _hex_digest(md5(text.encode("utf-8")).digest())


def _hex_digest(data: bytes) -> str:
    return "".join(hex(byte)[2:].zfill(2) for byte in data)


def _pick_url(value: str) -> str:
    match = _URL_RE.search(value)
    return match.group(0) if match else value


def _fragment_query(fragment: str) -> str:
    if not fragment:
        return ""
    if "?" in fragment:
        return fragment.split("?", 1)[1]
    return fragment
