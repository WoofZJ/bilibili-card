"""
小黑盒博文与评论 API 路由

端点:
  GET /xiaoheihe/post/info?share_url=...             返回博文 JSON
  GET /xiaoheihe/post/info/image?share_url=...       返回博文卡片图片
  GET /xiaoheihe/post/comments?share_url=...         返回评论 JSON
  GET /xiaoheihe/post/comments/image?share_url=...   返回评论卡片图片
"""

import hashlib
import re
import secrets
import time
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from log import archive_image, archive_json, logger
from xiaoheihe.models import XiaoheiheCommentsData, XiaoheihePostInfo, parse_xiaoheihe_emotes
from xiaoheihe.render import render_comments_to_bytes, render_post_to_bytes


router = APIRouter(prefix="/xiaoheihe", tags=["xiaoheihe"])

TREE_API = "https://api.xiaoheihe.cn/bbs/app/link/tree"
TREE_PATH = "/bbs/app/link/tree"
EMOJIS_API = "https://api.xiaoheihe.cn/bbs/app/api/emojis/list"
EMOJIS_PATH = "/bbs/app/api/emojis/list"
HKEY_ALPHABET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"

_CACHE_TTL = 60
_cache: dict[str, tuple[float, object]] = {}

_RATE_LIMIT_SECONDS = 5
_rate_limit_state: dict[str, float] = {}


def _client_identity(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(request: Request, bucket: str, interval: int = _RATE_LIMIT_SECONDS) -> None:
    now = time.monotonic()
    client = _client_identity(request)
    key = f"{bucket}:{client}"
    last_ts = _rate_limit_state.get(key)
    if last_ts is not None:
        wait = interval - (now - last_ts)
        if wait > 0:
            retry_after = max(1, int(wait + 0.999))
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请至少间隔 {interval} 秒后重试",
                headers={"Retry-After": str(retry_after)},
            )
    _rate_limit_state[key] = now


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def _extract_link_id(share_url: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{8,32}", share_url.strip()):
        return share_url.strip()

    parsed = urlparse(share_url)
    query = parse_qs(parsed.query)
    if "link_id" in query and query["link_id"]:
        return query["link_id"][0]

    match = re.search(r"/(?:app/bbs/link|bbs/link|link)/([0-9a-fA-F]+)", parsed.path)
    if match:
        return match.group(1)

    try:
        resp = requests.get(share_url, allow_redirects=True, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        final_url = resp.url
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析分享链接中的 link_id: {exc}") from exc

    if final_url != share_url:
        return _extract_link_id(final_url)
    raise HTTPException(status_code=400, detail="无法解析分享链接中的 link_id")


def _vm(value: int) -> int:
    return 255 & ((value << 1) ^ 27) if 128 & value else value << 1


def _qm(value: int) -> int:
    return _vm(value) ^ value


def _sm(value: int) -> int:
    return _qm(_vm(value))


def _ym(value: int) -> int:
    return _sm(_qm(_vm(value)))


def _gm(value: int) -> int:
    return _ym(value) ^ _sm(value) ^ _qm(value)


def _km(values: list[int]) -> list[int]:
    result = values[:]
    result[0] = _gm(values[0]) ^ _ym(values[1]) ^ _sm(values[2]) ^ _qm(values[3])
    result[1] = _qm(values[0]) ^ _gm(values[1]) ^ _ym(values[2]) ^ _sm(values[3])
    result[2] = _sm(values[0]) ^ _qm(values[1]) ^ _gm(values[2]) ^ _ym(values[3])
    result[3] = _ym(values[0]) ^ _sm(values[1]) ^ _qm(values[2]) ^ _gm(values[3])
    return result


def _map_chars(value: str, alphabet: str, end: int | None = None) -> str:
    source = alphabet[:end]
    return "".join(source[ord(char) % len(source)] for char in value)


def _interleave(values: list[str]) -> str:
    result = []
    max_len = max(len(value) for value in values)
    for index in range(max_len):
        for value in values:
            if index < len(value):
                result.append(value[index])
    return "".join(result)


def _build_hkey(path: str, timestamp: int, nonce: str) -> str:
    normalized_path = "/" + "/".join(part for part in path.split("/") if part) + "/"
    mixed = _interleave(
        [
            _map_chars(str(timestamp + 1), HKEY_ALPHABET, -2),
            _map_chars(normalized_path, HKEY_ALPHABET),
            _map_chars(nonce, HKEY_ALPHABET),
        ]
    )[:20]
    digest = hashlib.md5(mixed.encode()).hexdigest()
    checksum = str(sum(_km([ord(char) for char in digest[-6:]])) % 100).zfill(2)
    prefix = _map_chars(digest[:5], HKEY_ALPHABET, -4)
    return f"{prefix}{checksum}"


def _build_base_params(path: str) -> dict:
    timestamp = int(time.time())
    nonce = secrets.token_hex(16).upper()
    return {
        "os_type": "web",
        "app": "heybox",
        "client_type": "web",
        "version": "999.0.4",
        "web_version": "2.5",
        "x_client_type": "web",
        "x_app": "heybox_website",
        "heybox_id": "",
        "x_os_type": "Windows",
        "device_info": "Edge",
        "device_id": "9f11d127df1cd10466a076427872c105",
        "hkey": _build_hkey(path, timestamp, nonce),
        "_time": timestamp,
        "nonce": nonce,
    }


def _build_tree_params(link_id: str, page: int = 1, limit: int = 20) -> dict:
    params = _build_base_params(TREE_PATH)
    params.update({
        "link_id": link_id,
        "is_first": 1 if page == 1 else 0,
        "page": page,
        "index": (page - 1) * limit + 1,
        "limit": limit,
        "owner_only": 0,
    })
    return params


async def _fetch_tree_raw(share_url: str, page: int = 1, limit: int = 20) -> dict:
    link_id = _extract_link_id(share_url)
    cache_key = f"xhh_tree:{link_id}:{page}:{limit}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: xiaoheihe link_id=%s", link_id)
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
        "Origin": "https://www.xiaoheihe.cn",
    }
    try:
        resp = requests.get(
            TREE_API,
            params=_build_tree_params(link_id, page=page, limit=limit),
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        logger.error("小黑盒 API 请求失败: link_id=%s: %s", link_id, exc)
        raise HTTPException(status_code=502, detail=f"获取小黑盒数据失败: {exc}") from exc

    if raw.get("status") != "ok":
        detail = raw.get("msg") or "小黑盒 API 返回失败"
        raise HTTPException(status_code=502, detail=detail)

    archive_json("xiaoheihe", "post_info", link_id, raw)
    _cache_set(cache_key, raw, ttl=120)
    return raw


async def _fetch_emotes() -> dict:
    cache_key = "xhh_emotes"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.xiaoheihe.cn/",
        "Origin": "https://www.xiaoheihe.cn",
    }
    try:
        resp = requests.get(
            EMOJIS_API,
            params=_build_base_params(EMOJIS_PATH),
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        logger.warning("小黑盒表情列表请求失败: %s", exc)
        return {}

    if raw.get("status") != "ok":
        logger.warning("小黑盒表情列表返回失败: %s", raw.get("msg") or raw)
        return {}

    emotes = parse_xiaoheihe_emotes(raw)
    archive_json("xiaoheihe", "emojis", "list", raw)
    _cache_set(cache_key, emotes, ttl=24 * 60 * 60)
    return emotes


async def _fetch_post(share_url: str) -> XiaoheihePostInfo:
    raw = await _fetch_tree_raw(share_url)
    post = XiaoheihePostInfo.from_api(raw.get("result", {}))
    if not post.link_id:
        post.link_id = _extract_link_id(share_url)
    return post


async def _fetch_comments(share_url: str, limit: int = 20) -> XiaoheiheCommentsData:
    raw = await _fetch_tree_raw(share_url, limit=limit)
    comments = XiaoheiheCommentsData.from_api(raw)
    if not comments.link_id:
        comments.link_id = _extract_link_id(share_url)
    comments.emotes = await _fetch_emotes()
    archive_json("xiaoheihe", "comments", comments.link_id or "post", raw)
    return comments


@router.get("/post/info", response_model=XiaoheihePostInfo, summary="根据分享链接获取小黑盒博文")
async def get_post_info(
    request: Request,
    share_url: str = Query(..., description="小黑盒分享链接或 link_id"),
):
    _enforce_rate_limit(request, "xhh/post/info")
    return await _fetch_post(share_url)


@router.get("/post/info/image", summary="根据分享链接获取小黑盒博文卡片图片")
async def get_post_info_image(
    request: Request,
    share_url: str = Query(..., description="小黑盒分享链接或 link_id"),
):
    _enforce_rate_limit(request, "xhh/post/info/image")
    post = await _fetch_post(share_url)
    img_bytes = render_post_to_bytes(post)
    archive_image("xiaoheihe", post.link_id or "post", img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/post/comments", response_model=XiaoheiheCommentsData, summary="根据分享链接获取小黑盒评论")
async def get_post_comments(
    request: Request,
    share_url: str = Query(..., description="小黑盒分享链接或 link_id"),
    limit: int = Query(20, description="评论页大小", ge=1, le=50),
):
    _enforce_rate_limit(request, "xhh/post/comments")
    return await _fetch_comments(share_url, limit=limit)


@router.get("/post/comments/image", summary="根据分享链接获取小黑盒评论卡片图片")
async def get_post_comments_image(
    request: Request,
    share_url: str = Query(..., description="小黑盒分享链接或 link_id"),
    limit: int = Query(20, description="请求评论数量", ge=1, le=50),
    max_comments: int = Query(4, description="图片中最多显示评论数，按点赞数排序", ge=1, le=4),
):
    _enforce_rate_limit(request, "xhh/post/comments/image")
    comments = await _fetch_comments(share_url, limit=limit)
    if not comments.comments:
        raise HTTPException(status_code=404, detail="该博文没有可见评论")
    img_bytes = render_comments_to_bytes(comments, max_comments=max_comments)
    archive_image("xiaoheihe", f"{comments.link_id or 'post'}_comments", img_bytes)
    return Response(content=img_bytes, media_type="image/png")
