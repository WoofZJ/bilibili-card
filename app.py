"""
B站视频信息 Web API

启动: uvicorn app:app --reload --host 0.0.0.0 --port 8000

API 端点:
  GET  /video/latest?user_id=xxx          返回最新视频 JSON
  GET  /video/latest/image?user_id=xxx    返回最新视频信息卡片图片
  GET  /video/info?bvid=xxx               根据BV号返回视频 JSON
  GET  /video/info/image?bvid=xxx         根据BV号返回视频信息卡片图片
  GET  /health                            健康检查
"""

import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import Response

from bilibili_api import request_settings, select_client, user, video, search, get_real_url, comment

from models import VideoInfo, CommentsData
from render import render_to_bytes, render_comments_to_bytes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化 bilibili_api 客户端"""
    request_settings.set("impersonate", "safari")
    # with open(".env", "r", encoding="utf-8") as f:
    #     for line in f:
    #         if line.startswith("PROXY="):
    #             proxy = line.strip().split("=", 1)[1].strip('"')
    #             request_settings.set_proxy(proxy)
    #             break
    select_client("curl_cffi")
    print("bilibili_api 客户端已初始化")
    yield


app = FastAPI(
    title="B站视频信息 API",
    description="获取B站用户最新视频信息，支持JSON和卡片图片输出",
    version="1.0.0",
    lifespan=lifespan,
)


# ── 缓存 ──────────────────────────────────────────
_CACHE_TTL = 60  # 缓存有效期（秒）
_cache: dict[str, tuple[float, VideoInfo]] = {}  # key -> (expire_ts, data)


def _cache_get(key: str) -> VideoInfo | None:
    """获取未过期的缓存条目"""
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: VideoInfo, ttl: int = _CACHE_TTL) -> None:
    """写入缓存"""
    _cache[key] = (time.monotonic() + ttl, value)

def log(file_name: str, message: str) -> None:
    """简单日志函数，写入指定文件"""
    with open(file_name, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

# ── 业务逻辑 ─────────────────────────────────────
async def _fetch_latest_video(user_id: int) -> VideoInfo:
    """获取指定用户的最新视频信息（带缓存）"""
    cache_key = f"latest:{user_id}"
    if cached := _cache_get(cache_key):
        log("fetch_latest_video.log", f"Cache hit for user_id={user_id}")
        return cached

    try:
        u = user.User(user_id)
        page = await u.get_videos(ps=1)
        log("fetch_latest_video.log", f"API call completed for user_id={user_id}")
        time.sleep(5)
    except Exception as e:
        log("fetch_latest_video.log", f"API call failed for user_id={user_id}: {e}")
        raise HTTPException(status_code=502, detail=f"获取视频列表失败: {e}")

    vlist = page.get("list", {}).get("vlist", [])
    if not vlist:
        log("fetch_latest_video.log", f"No videos found for user_id={user_id}")
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 没有投稿视频")

    bvid = vlist[0]["bvid"]
    result = await _fetch_video_by_bvid(bvid)
    _cache_set(cache_key, result)
    return result


async def _fetch_video_by_bvid(bvid: str) -> VideoInfo:
    """根据 BV 号获取视频详细信息（带缓存）"""
    cache_key = f"bvid:{bvid}"
    if cached := _cache_get(cache_key):
        return cached

    try:
        v = video.Video(bvid)
        info = await v.get_info()
        danmakus = await v.get_danmaku_snapshot()
        if not os.path.exists("output/video_info"):
            os.makedirs("output/video_info")
        with open(f"output/video_info/{bvid}_{time.strftime('%Y%m%d%H%M%S', time.localtime())}.json", "w", encoding="utf-8") as f:
            import json
            json.dump(info, f, ensure_ascii=False, indent=2)
        log("fetch_video_by_bvid.log", f"API call completed for bvid={bvid}")

    except Exception as e:
        log("fetch_video_by_bvid.log", f"API call failed for bvid={bvid}: {e}")
        raise HTTPException(status_code=502, detail=f"获取视频信息失败: {e}")
    result = VideoInfo.from_api(info)
    _cache_set(cache_key, result, ttl=60*60)
    # 缓存弹幕快照（文本列表）
    danmaku_texts = [str(d) for d in danmakus] if danmakus else []
    _cache_set(f"danmaku:{bvid}", danmaku_texts, ttl=60*60)
    return result

async def _fetch_uid_by_name(username: str) -> int:
    """根据用户名获取用户ID"""
    cache_key = f"uid:{username}"
    if cached := _cache_get(cache_key):
        return cached

    try:
        result = await search.search_by_type(keyword=username, search_type=search.SearchObjectType.USER, page=1, page_size=5, order_type=search.OrderUser.FANS)
        user_list = result["result"]
        user_name = user_list[0]["uname"]
        user_id = user_list[0]["mid"]
        fans = user_list[0]["fans"]
        result = {"username": user_name, "user_id": user_id, "fans": fans}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取用户信息失败: {e}")
    _cache_set(cache_key, result, ttl=60*60*24)
    return result

async def _fetch_video_by_short_url(short_url: str) -> VideoInfo:
    """根据短链接获取视频信息"""
    cache_key = f"short_link:{short_url}"
    print(cache_key)
    if cached := _cache_get(cache_key):
        real_url = cached
    else:
        real_url = await get_real_url(short_url)
        _cache_set(cache_key, real_url, ttl=24*60*60)

    print(f"Real URL for {short_url}: {real_url}")
    bvid = real_url.split("?")[0].strip("/").split("/")[-1]
    return await _fetch_video_by_bvid(bvid)

# ── API 端点 ──────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/video/latest", response_model=VideoInfo, summary="获取用户最新视频信息")
async def get_latest_video(user_id: int = Query(..., description="B站用户ID", examples=[1137066730])):
    return await _fetch_latest_video(user_id)


@app.get("/video/latest/image", summary="获取用户最新视频信息卡片图片")
async def get_latest_video_image(user_id: int = Query(..., description="B站用户ID", examples=[1137066730])):
    video_info = await _fetch_latest_video(user_id)
    danmaku_list = _cache_get(f"danmaku:{video_info.bvid}")
    img_bytes = render_to_bytes(video_info, danmaku_list=danmaku_list)
    if not os.path.exists("output/image"):
        os.makedirs("output/image")
    output_path = f"output/image/{video_info.bvid}_{time.strftime('%Y%m%d%H%M%S', time.localtime())}.png"
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@app.get("/video/info", response_model=VideoInfo, summary="根据BV号获取视频信息")
async def get_video_info(bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"])):
    print(f"Received request for video info with bvid={bvid}")
    return await _fetch_video_by_bvid(bvid)


@app.get("/video/info/image", summary="根据BV号获取视频信息卡片图片")
async def get_video_info_image(bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"])):
    video_info = await _fetch_video_by_bvid(bvid)
    danmaku_list = _cache_get(f"danmaku:{bvid}")
    img_bytes = render_to_bytes(video_info, danmaku_list=danmaku_list)
    if not os.path.exists("output/image"):
        os.makedirs("output/image")
    output_path = f"output/image/{bvid}_{time.strftime('%Y%m%d%H%M%S', time.localtime())}.png"
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    return Response(content=img_bytes, media_type="image/png")

@app.get("/user/id", summary="根据用户名获取用户ID")
async def get_user_id(username: str = Query(..., description="B站用户名", examples=["某某UP主"])):
    return await _fetch_uid_by_name(username)

@app.get("/video/info/short_url", summary="根据短链接获取视频信息")
async def get_video_info_short_url(short_url: str = Query(..., description="视频短链接", examples=["https://b23.tv/xxxx"])):
    return await _fetch_video_by_short_url(short_url)


# ── 评论相关 ──────────────────────────────────────
async def _fetch_comments(bvid: str) -> CommentsData:
    """获取视频评论数据（带缓存）"""
    cache_key = f"comments:{bvid}"
    if cached := _cache_get(cache_key):
        return cached

    try:
        v = video.Video(bvid)
        aid = v.get_aid()
        comments_raw = await comment.get_comments_lazy(
            aid, type_=comment.CommentResourceType.VIDEO, order=comment.OrderType.LIKE
        )
        if not os.path.exists("output/comments"):
            os.makedirs("output/comments")
        with open(f"output/comments/{bvid}_{time.strftime('%Y%m%d%H%M%S', time.localtime())}.json", "w", encoding="utf-8") as f:
            import json
            json.dump(comments_raw, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取评论失败: {e}")

    result = CommentsData.from_api(comments_raw)
    _cache_set(cache_key, result, ttl=120)
    return result


@app.get("/video/comments", summary="获取视频热门评论 JSON")
async def get_video_comments(bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"])):
    return await _fetch_comments(bvid)


@app.get("/video/comments/image", summary="获取视频热门评论卡片图片")
async def get_video_comments_image(
    bvid: str = Query(..., description="视频BV号", examples=["BV1VYf3BiEKJ"]),
    max_comments: int = Query(15, description="最多显示评论数", ge=1, le=50),
):
    comments_data = await _fetch_comments(bvid)
    if comments_data.total == 0 or (not comments_data.top_comment and not comments_data.comments):
        raise HTTPException(status_code=404, detail="该视频没有可见评论")
    img_bytes = render_comments_to_bytes(comments_data, max_comments=max_comments)
    if not os.path.exists("output/image"):
        os.makedirs("output/image")
    output_path = f"output/image/comments_{bvid}_{time.strftime('%Y%m%d%H%M%S', time.localtime())}.png"
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    return Response(content=img_bytes, media_type="image/png")