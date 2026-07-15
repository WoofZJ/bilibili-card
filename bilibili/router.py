"""
B站视频信息 API 路由

端点:
  GET  /video/latest?user_id=xxx          返回最新视频 JSON
  GET  /video/latest/image?user_id=xxx    返回最新视频信息卡片图片
  GET  /video/info?bvid=xxx               根据BV号返回视频 JSON
  GET  /video/info/image?bvid=xxx         根据BV号返回视频信息卡片图片
  GET  /video/info/short_url?short_url=xx 根据短链接获取视频信息
  GET  /user/id?username=xxx              根据用户名获取用户ID
  GET  /video/comments?bvid=xxx           获取视频热门评论 JSON
  GET  /video/comments/image?bvid=xxx     获取视频热门评论卡片图片
  GET  /opus/info/image?opus_id=xxx       获取图文卡片图片
  GET  /opus/images?opus_id=xxx           获取图文正文全部图片 JSON
  GET  /live/room?room_id=xxx             获取直播间 JSON
  GET  /live/room/image?room_id=xxx       获取直播间卡片图片
"""

import os
import time
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import Response
from dotenv import load_dotenv

from bilibili_api import user, video, search, get_real_url, comment, live, opus, Credential

from bilibili.models import VideoInfo, LiveRoomInfo, CommentsData, OpusInfo
from bilibili.render import (
    render_to_bytes,
    render_live_room_to_bytes,
    render_comments_to_bytes,
    render_opus_to_bytes,
)
from log import logger, archive_json, archive_image


router = APIRouter(prefix="/bilibili", tags=["bilibili"])


# ── B站凭证 ───────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_PATH)


def _env_value(*names: str):
    """按候选变量名从环境中读取第一个非空值。"""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


_credential_fields = {
    "sessdata": _env_value("SESSDATA", "SESSION_DATA", "BILI_SESSDATA"),
    "bili_jct": _env_value("BILI_JCT", "bili_jct"),
    "buvid3": _env_value("BUVID3", "buvid3"),
    "buvid4": _env_value("BUVID4", "buvid4"),
    "dedeuserid": _env_value("DEDEUSERID", "DEDE_USER_ID", "DedeUserID"),
    "ac_time_value": _env_value("AC_TIME_VALUE", "ac_time_value"),
}
_credential = Credential(**_credential_fields)

_loaded_credential_fields = [
    name for name, value in _credential_fields.items() if value
]
if _loaded_credential_fields:
    logger.info("B站 Credential 已加载字段: %s", ", ".join(_loaded_credential_fields))
else:
    logger.warning("B站 Credential 未配置，将使用匿名凭证调用公开 API")


# ── 缓存 ──────────────────────────────────────────
_CACHE_TTL = 60  # 缓存有效期（秒）
_cache: dict[str, tuple[float, object]] = {}  # key -> (expire_ts, data)

# ── 频率限制 ─────────────────────────────────────
_RATE_LIMIT_SECONDS = 5
_rate_limit_state: dict[str, float] = {}

def _client_identity(request: Request) -> str:
    """提取客户端标识，优先使用反向代理透传的真实IP。"""
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(request: Request, bucket: str, interval: int = _RATE_LIMIT_SECONDS) -> None:
    """限制同一客户端对同一资源的最小调用间隔。"""
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
                bucket,
                client,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请至少间隔 {interval} 秒后重试",
                headers={"Retry-After": str(retry_after)},
            )
    _rate_limit_state[key] = now


def _cache_get(key: str):
    """获取未过期的缓存条目"""
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL) -> None:
    """写入缓存"""
    _cache[key] = (time.monotonic() + ttl, value)


# ── 业务逻辑 ─────────────────────────────────────
async def _fetch_latest_video(user_id: int) -> VideoInfo:
    """获取指定用户的最新视频信息（带缓存）"""
    cache_key = f"latest:{user_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: latest user_id=%s", user_id)
        return cached

    try:
        u = user.User(user_id, credential=_credential)
        page = await u.get_videos(ps=1)
        logger.info("API 请求完成: get_videos user_id=%s", user_id)
    except Exception as e:
        logger.error("API 请求失败: get_videos user_id=%s: %s", user_id, e)
        raise HTTPException(status_code=502, detail=f"获取视频列表失败: {e}")

    vlist = page.get("list", {}).get("vlist", [])
    if not vlist:
        logger.warning("用户无投稿: user_id=%s", user_id)
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 没有投稿视频")

    bvid = vlist[0]["bvid"]
    result = await _fetch_video_by_bvid(bvid)
    _cache_set(cache_key, result)
    return result


async def _fetch_video_by_bvid(bvid: str) -> VideoInfo:
    """根据 BV 号获取视频详细信息（带缓存）"""
    cache_key = f"bvid:{bvid}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: video bvid=%s", bvid)
        return cached

    try:
        v = video.Video(bvid=bvid)
        info = await v.get_info()
        danmakus = await v.get_danmaku_snapshot()
        archive_json("bilibili", "video_info", bvid, info)
        logger.info("API 请求完成: get_info bvid=%s", bvid)
    except Exception as e:
        logger.error("API 请求失败: get_info bvid=%s: %s", bvid, e)
        raise HTTPException(status_code=502, detail=f"获取视频信息失败: {e}")
    result = VideoInfo.from_api(info)
    _cache_set(cache_key, result, ttl=60*60)
    # 缓存弹幕快照（文本列表）
    danmaku_texts = [str(d) for d in danmakus] if danmakus else []
    _cache_set(f"danmaku:{bvid}", danmaku_texts, ttl=60*60)
    return result


async def _fetch_uid_by_name(username: str):
    """根据用户名获取用户ID"""
    cache_key = f"uid:{username}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: uid username=%s", username)
        return cached

    try:
        result = await search.search_by_type(keyword=username, search_type=search.SearchObjectType.USER, page=1, page_size=5, order_type=search.OrderUser.FANS)
        user_list = result["result"]
        user_name = user_list[0]["uname"]
        user_id = user_list[0]["mid"]
        fans = user_list[0]["fans"]
        result = {"username": user_name, "user_id": user_id, "fans": fans}
        logger.info("API 请求完成: search_user username=%s -> uid=%s", username, user_id)
    except Exception as e:
        logger.error("API 请求失败: search_user username=%s: %s", username, e)
        raise HTTPException(status_code=502, detail=f"获取用户信息失败: {e}")
    _cache_set(cache_key, result, ttl=60*60*24)
    return result


async def _fetch_video_by_short_url(short_url: str) -> VideoInfo:
    """根据短链接获取视频信息"""
    cache_key = f"short_link:{short_url}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: short_link=%s", short_url)
        real_url = cached
    else:
        real_url = await get_real_url(short_url)
        logger.info("短链接解析: %s -> %s", short_url, real_url)
        _cache_set(cache_key, real_url, ttl=24*60*60)

    bvid = real_url.split("?")[0].strip("/").split("/")[-1]
    return await _fetch_video_by_bvid(bvid)


async def _fetch_comments(bvid: str) -> CommentsData:
    """获取视频评论数据（带缓存）"""
    cache_key = f"comments:{bvid}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: comments bvid=%s", bvid)
        return cached

    try:
        v = video.Video(bvid=bvid)
        aid = v.get_aid()
        comments_raw = await comment.get_comments_lazy(
            aid,
            type_=comment.CommentResourceType.VIDEO,
            order=comment.OrderType.LIKE
        )
        archive_json("bilibili", "comments", bvid, comments_raw)
        logger.info("API 请求完成: get_comments bvid=%s", bvid)
    except Exception as e:
        logger.error("API 请求失败: get_comments bvid=%s: %s", bvid, e)
        raise HTTPException(status_code=502, detail=f"获取评论失败: {e}")

    result = CommentsData.from_api(comments_raw)
    _cache_set(cache_key, result, ttl=120)
    return result


async def _fetch_live_room(room_id: int) -> LiveRoomInfo:
    """获取直播间信息（带缓存）"""
    cache_key = f"live_room:{room_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: live_room room_id=%s", room_id)
        return cached

    try:
        room = live.LiveRoom(room_id, credential=_credential)
        info = await room.get_room_info()
        archive_json("bilibili", "live_room_info", str(room_id), info)
        logger.info("API 请求完成: get_room_info room_id=%s", room_id)
    except Exception as e:
        logger.error("API 请求失败: get_room_info room_id=%s: %s", room_id, e)
        raise HTTPException(status_code=502, detail=f"获取直播间信息失败: {e}")

    result = LiveRoomInfo.from_api(info)
    _cache_set(cache_key, result, ttl=30)
    return result


async def _fetch_opus_info(opus_id: int) -> OpusInfo:
    """获取图文详情并转换为卡片渲染模型（带缓存）。"""
    cache_key = f"opus_info:{opus_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("缓存命中: opus info opus_id=%s", opus_id)
        return cached

    try:
        opus_item = opus.Opus(opus_id, credential=_credential)
        raw = await opus_item.get_info()
        archive_json("bilibili", "opus_info", str(opus_id), raw)
        logger.info("API 请求完成: opus.get_info opus_id=%s", opus_id)
    except Exception as exc:
        logger.error("API 请求失败: opus.get_info opus_id=%s: %s", opus_id, exc)
        raise HTTPException(status_code=502, detail=f"获取图文信息失败: {exc}") from exc

    result = OpusInfo.from_api(raw)
    if result.opus_id <= 0:
        result.opus_id = opus_id
    _cache_set(cache_key, result, ttl=60 * 60)
    return result


async def _fetch_opus_images(opus_id: int) -> list[dict]:
    """获取图文正文中的全部图片原始信息（带缓存）。"""
    cache_key = f"opus_images:{opus_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("缓存命中: opus images opus_id=%s", opus_id)
        return cached

    try:
        opus_item = opus.Opus(opus_id, credential=_credential)
        images = await opus_item.get_images_raw_info()
        if not isinstance(images, list):
            raise TypeError("图文图片接口返回了非列表数据")
        archive_json("bilibili", "opus_images", str(opus_id), images)
        logger.info("API 请求完成: opus.get_images_raw_info opus_id=%s count=%s", opus_id, len(images))
    except Exception as exc:
        logger.error("API 请求失败: opus.get_images_raw_info opus_id=%s: %s", opus_id, exc)
        raise HTTPException(status_code=502, detail=f"获取图文图片失败: {exc}") from exc

    _cache_set(cache_key, images, ttl=60 * 60)
    return images


# ── API 端点 ──────────────────────────────────────
@router.get("/video/latest", response_model=VideoInfo, summary="获取用户最新视频信息")
async def get_latest_video(
    request: Request,
    user_id: int = Query(..., description="B站用户ID", examples=[1137066730]),
):
    _enforce_rate_limit(request, "video/latest")
    return await _fetch_latest_video(user_id)


@router.get("/video/latest/image", summary="获取用户最新视频信息卡片图片")
async def get_latest_video_image(
    request: Request,
    user_id: int = Query(..., description="B站用户ID", examples=[1137066730]),
):
    _enforce_rate_limit(request, "video/latest/image")
    video_info = await _fetch_latest_video(user_id)
    danmaku_list = _cache_get(f"danmaku:{video_info.bvid}")
    img_bytes = render_to_bytes(video_info, danmaku_list=danmaku_list)
    archive_image("bilibili", video_info.bvid, img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/video/info", response_model=VideoInfo, summary="根据BV号获取视频信息")
async def get_video_info(
    request: Request,
    bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"]),
):
    _enforce_rate_limit(request, "video/info")
    logger.info("收到请求: /video/info bvid=%s", bvid)
    return await _fetch_video_by_bvid(bvid)


@router.get("/video/info/image", summary="根据BV号获取视频信息卡片图片")
async def get_video_info_image(
    request: Request,
    bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"]),
):
    _enforce_rate_limit(request, "video/info/image")
    video_info = await _fetch_video_by_bvid(bvid)
    danmaku_list = _cache_get(f"danmaku:{bvid}")
    img_bytes = render_to_bytes(video_info, danmaku_list=danmaku_list)
    archive_image("bilibili", bvid, img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/user/id", summary="根据用户名获取用户ID")
async def get_user_id(
    request: Request,
    username: str = Query(..., description="B站用户名", examples=["某某UP主"]),
):
    _enforce_rate_limit(request, "user/id")
    return await _fetch_uid_by_name(username)


@router.get("/video/info/short_url", summary="根据短链接获取视频信息")
async def get_video_info_short_url(
    request: Request,
    short_url: str = Query(..., description="视频短链接", examples=["https://b23.tv/xxxx"]),
):
    _enforce_rate_limit(request, "video/info/short_url")
    return await _fetch_video_by_short_url(short_url)


@router.get("/video/comments", summary="获取视频热门评论 JSON")
async def get_video_comments(
    request: Request,
    bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"]),
):
    _enforce_rate_limit(request, "video/comments")
    return await _fetch_comments(bvid)


@router.get("/video/comments/image", summary="获取视频热门评论卡片图片")
async def get_video_comments_image(
    request: Request,
    bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"]),
    max_comments: int = Query(4, description="最多显示评论数", ge=1, le=50),
):
    _enforce_rate_limit(request, "video/comments/image")
    comments_data = await _fetch_comments(bvid)
    if comments_data.total == 0 or (not comments_data.top_comment and not comments_data.comments):
        raise HTTPException(status_code=404, detail="该视频没有可见评论")
    img_bytes = render_comments_to_bytes(comments_data, max_comments=max_comments)
    archive_image("bilibili", f"{bvid}_comments", img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/opus/info/image", summary="根据 opus_id 获取B站图文卡片图片")
async def get_opus_info_image(
    request: Request,
    opus_id: int = Query(..., description="B站图文 opus_id", gt=0, examples=[1225199552930250752]),
):
    _enforce_rate_limit(request, "opus/info/image")
    opus_info = await _fetch_opus_info(opus_id)
    img_bytes = render_opus_to_bytes(opus_info)
    archive_image("bilibili", f"opus_{opus_id}", img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/opus/images", summary="根据 opus_id 获取B站图文中的全部图片")
async def get_opus_images(
    request: Request,
    opus_id: int = Query(..., description="B站图文 opus_id", gt=0, examples=[1225199552930250752]),
) -> list[dict]:
    _enforce_rate_limit(request, "opus/images")
    return await _fetch_opus_images(opus_id)


@router.get("/live/room", response_model=LiveRoomInfo, summary="获取直播间信息")
async def get_live_room(
    request: Request,
    room_id: int = Query(..., description="直播间房间号", examples=[1863475727]),
):
    _enforce_rate_limit(request, "live/room")
    return await _fetch_live_room(room_id)


@router.get("/live/room/image", summary="获取直播间卡片图片")
async def get_live_room_image(
    request: Request,
    room_id: int = Query(..., description="直播间房间号", examples=[1863475727]),
):
    _enforce_rate_limit(request, "live/room/image")
    live_room = await _fetch_live_room(room_id)
    img_bytes = render_live_room_to_bytes(live_room)
    archive_image("bilibili", f"live_{live_room.room_id or room_id}", img_bytes)
    return Response(content=img_bytes, media_type="image/png")

@router.get("/resolve", summary="解析任意B站短链接")
async def resolve_short_link(
    request: Request,
    short_url: str = Query(..., description="B站短链接", examples=["https://b23.tv/xxxx"]),
):
    real_url = await get_real_url(short_url)
    logger.info("短链接解析: %s -> %s", short_url, real_url)
    return real_url
