"""
YouTube 视频信息 API 路由

端点:
  GET  /video/info?video_id=xxx            根据视频ID返回视频信息 JSON
  GET  /video/info/image?video_id=xxx      根据视频ID返回视频信息卡片图片
  GET  /video/info/url?url=xxx             根据YouTube链接获取视频信息 JSON
  GET  /video/info/url/image?url=xxx       根据YouTube链接获取视频信息卡片图片
  GET  /video/comments?video_id=xxx        根据视频ID获取评论 JSON
  GET  /video/comments/image?video_id=xxx  根据视频ID获取评论卡片图片
"""

import os
import re
import time

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import Response

from youtube.models import YouTubeVideoInfo, YouTubeCommentsData
from youtube.render import render_to_bytes, render_comments_to_bytes
from log import logger, archive_json, archive_image


router = APIRouter(prefix="/youtube", tags=["youtube"])

# ── YouTube API Key ──────────────────────────────
_YTB_KEY: str | None = None


def _load_api_key() -> str:
    """从环境变量或 .env 文件加载 YouTube API Key"""
    global _YTB_KEY
    if _YTB_KEY:
        return _YTB_KEY

    # 优先从环境变量获取
    key = os.environ.get("YTB_KEY", "")
    if not key:
        # 尝试从 .env 文件读取
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f.read().splitlines():
                    if line.startswith("YTB_KEY="):
                        key = line.split("=", 1)[1].strip("'").strip('"')
                        break

    if not key:
        raise HTTPException(status_code=503, detail="YouTube API Key 未配置，请设置 YTB_KEY 环境变量或 .env 文件")

    _YTB_KEY = key
    return key


# ── 缓存 ──────────────────────────────────────────
_CACHE_TTL = 60
_cache: dict[str, tuple[float, object]] = {}

# ── 频率限制 ─────────────────────────────────────
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
            logger.warning(
                "请求被限流: bucket=%s client=%s retry_after=%ss",
                bucket, client, retry_after,
            )
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


# ── 视频ID解析 ───────────────────────────────────
_YOUTUBE_URL_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})"),
]


def _extract_video_id(url: str) -> str:
    """从 YouTube URL 中提取视频 ID"""
    for pattern in _YOUTUBE_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    raise HTTPException(status_code=400, detail=f"无法从 URL 中解析视频 ID: {url}")


# ── 业务逻辑 ─────────────────────────────────────
async def _fetch_video_by_id(video_id: str) -> YouTubeVideoInfo:
    """根据视频 ID 获取视频信息（带缓存，含频道头像）"""
    cache_key = f"yt_video:{video_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: youtube video_id=%s", video_id)
        return cached

    import requests

    api_key = _load_api_key()
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,statistics,contentDetails,localizations",
        "id": video_id,
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        archive_json("youtube", "video_info", video_id, raw)
        logger.info("YouTube API 请求完成: videos.list video_id=%s", video_id)
    except Exception as e:
        logger.error("YouTube API 请求失败: videos.list video_id=%s: %s", video_id, e)
        raise HTTPException(status_code=502, detail=f"获取视频信息失败: {e}")

    if not raw.get("items"):
        raise HTTPException(status_code=404, detail=f"视频 {video_id} 不存在")

    result = YouTubeVideoInfo.from_api(raw)

    # 获取频道头像
    channel_avatar = await _fetch_channel_avatar(result.channel_id)
    if channel_avatar:
        result.channel_avatar = channel_avatar

    _cache_set(cache_key, result, ttl=60 * 60)
    return result


async def _fetch_channel_avatar(channel_id: str) -> str:
    """获取频道头像 URL（带缓存）"""
    if not channel_id:
        return ""

    cache_key = f"yt_channel_avatar:{channel_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: youtube channel_avatar channel_id=%s", channel_id)
        return cached

    import requests

    api_key = _load_api_key()
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "snippet",
        "id": channel_id,
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        avatar_url = YouTubeVideoInfo.extract_channel_avatar(raw)
        logger.info("YouTube API 请求完成: channels.list channel_id=%s", channel_id)
    except Exception as e:
        logger.warning("YouTube API 频道头像获取失败: channel_id=%s: %s", channel_id, e)
        return ""

    _cache_set(cache_key, avatar_url, ttl=24 * 60 * 60)
    return avatar_url


# ── API 端点 ──────────────────────────────────────
@router.get("/video/info", response_model=YouTubeVideoInfo, summary="根据视频ID获取YouTube视频信息")
async def get_video_info(
    request: Request,
    video_id: str = Query(..., description="YouTube视频ID", examples=["DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/info")
    logger.info("收到请求: /youtube/video/info video_id=%s", video_id)
    return await _fetch_video_by_id(video_id)


@router.get("/video/info/image", summary="根据视频ID获取YouTube视频信息卡片图片")
async def get_video_info_image(
    request: Request,
    video_id: str = Query(..., description="YouTube视频ID", examples=["DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/info/image")
    video_info = await _fetch_video_by_id(video_id)
    img_bytes = render_to_bytes(video_info)
    archive_image("youtube", video_id, img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/video/info/url", response_model=YouTubeVideoInfo, summary="根据YouTube链接获取视频信息")
async def get_video_info_by_url(
    request: Request,
    url: str = Query(..., description="YouTube视频链接", examples=["https://youtu.be/DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/info/url")
    video_id = _extract_video_id(url)
    return await _fetch_video_by_id(video_id)


@router.get("/video/info/url/image", summary="根据YouTube链接获取视频信息卡片图片")
async def get_video_info_by_url_image(
    request: Request,
    url: str = Query(..., description="YouTube视频链接", examples=["https://youtu.be/DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/info/url")
    video_id = _extract_video_id(url)
    video_info = await _fetch_video_by_id(video_id)
    img_bytes = render_to_bytes(video_info)
    archive_image("youtube", video_id, img_bytes)
    return Response(content=img_bytes, media_type="image/png")


# ── 评论业务逻辑 ─────────────────────────────────
async def _fetch_comments(video_id: str, max_results: int = 20) -> YouTubeCommentsData:
    """获取视频评论（带缓存）"""
    cache_key = f"yt_comments:{video_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: youtube comments video_id=%s", video_id)
        return cached

    import requests

    api_key = _load_api_key()
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet,replies",
        "videoId": video_id,
        "maxResults": max_results,
        "order": "relevance",
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        archive_json("youtube", "comments", video_id, raw)
        logger.info("YouTube API 请求完成: commentThreads.list video_id=%s", video_id)
    except Exception as e:
        logger.error("YouTube API 请求失败: commentThreads.list video_id=%s: %s", video_id, e)
        raise HTTPException(status_code=502, detail=f"获取评论失败: {e}")

    result = YouTubeCommentsData.from_api(raw)
    _cache_set(cache_key, result, ttl=60 * 5)
    return result


@router.get("/video/comments", summary="根据视频ID获取YouTube视频评论")
async def get_video_comments(
    request: Request,
    video_id: str = Query(..., description="YouTube视频ID", examples=["DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/comments")
    logger.info("收到请求: /youtube/video/comments video_id=%s", video_id)
    return await _fetch_comments(video_id)


@router.get("/video/comments/image", summary="根据视频ID获取YouTube评论卡片图片")
async def get_video_comments_image(
    request: Request,
    video_id: str = Query(..., description="YouTube视频ID", examples=["DEVIeLuFXQY"]),
):
    _enforce_rate_limit(request, "yt/video/comments/image")
    comments_data = await _fetch_comments(video_id)
    img_bytes = render_comments_to_bytes(comments_data)
    archive_image("youtube", video_id + "_comments", img_bytes)
    return Response(content=img_bytes, media_type="image/png")
