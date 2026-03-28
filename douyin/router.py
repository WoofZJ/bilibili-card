"""
抖音数据 API 路由

端点:
  GET  /user/info?user_sec_id=xxx         获取用户信息
  GET  /user/works?user_sec_id=xxx        获取用户全部作品
  GET  /work/info?url=xxx                 获取作品信息
  GET  /work/info/image?url=xxx           获取作品信息卡片图片
  GET  /work/comments?url=xxx             获取作品评论
  GET  /work/comments/image?url=xxx       获取作品评论卡片图片
"""

import time
import asyncio
from functools import partial

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response

from log import logger, archive_json, archive_image
from douyin.models import DouyinUserInfo, DouyinWorkInfo, DouyinCommentsData
from douyin.render import render_to_bytes, render_comments_to_bytes

router = APIRouter(prefix="/douyin", tags=["douyin"])

# ── 全局 auth（由 app lifespan 初始化） ────────────
_auth = None


def set_auth(auth):
    """由 app lifespan 调用，注入 DouyinAuth 实例"""
    global _auth
    _auth = auth


def _get_auth():
    if _auth is None:
        raise HTTPException(status_code=503, detail="抖音 API 未初始化，请检查 DY_COOKIES 配置")
    return _auth


async def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步函数"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


# ── 缓存 ──────────────────────────────────────────
_CACHE_TTL = 60  # 缓存有效期（秒）
_cache: dict[str, tuple[float, object]] = {}


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


# ── 短链解析 ─────────────────────────────────────
async def _resolve_short_url(url: str) -> str:
    """将 v.douyin.com 短链重定向为完整 URL（带缓存）"""
    if "v.douyin.com" not in url:
        return url

    cache_key = f"short_url:{url}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: short_url=%s", url)
        return cached

    import requests
    real_url = await _run_sync(requests.head, url, allow_redirects=True)
    resolved = real_url.url
    logger.info("短链接解析: %s -> %s", url, resolved)
    _cache_set(cache_key, resolved, ttl=24 * 60 * 60)
    return resolved


# ── 业务逻辑 ─────────────────────────────────────
async def _fetch_user_info(user_sec_id: str) -> DouyinUserInfo:
    """获取用户信息（带缓存）"""
    cache_key = f"dy_user:{user_sec_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: user_info sec_uid=%s", user_sec_id)
        return cached

    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_user_info, auth, f"https://www.douyin.com/user/{user_sec_id}")
        result = DouyinUserInfo.from_api(raw)
        logger.info("抖音 API 请求完成: get_user_info nickname=%s", result.nickname)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_user_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取用户信息失败: {e}")

    _cache_set(cache_key, result, ttl=60 * 60)
    return result


async def _fetch_user_works(user_sec_id: str) -> list[DouyinWorkInfo]:
    """获取用户全部作品（带缓存）"""
    cache_key = f"dy_works:{user_sec_id}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: user_works sec_uid=%s", user_sec_id)
        return cached

    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_user_all_work_info, auth, user_sec_id)
        result = DouyinWorkInfo.from_api_list(raw)
        logger.info("抖音 API 请求完成: get_user_all_work_info, 作品数=%d", len(result))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_user_all_work_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取用户作品失败: {e}")

    _cache_set(cache_key, result, ttl=5 * 60)
    return result


async def _fetch_work_info(url: str) -> DouyinWorkInfo:
    """获取作品信息（带缓存，自动解析短链）"""
    url = await _resolve_short_url(url)

    cache_key = f"dy_work:{url}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: work_info url=%s", url)
        return cached

    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_work_info, auth, url)
        aweme_detail = raw.get("aweme_detail", raw)
        result = DouyinWorkInfo.from_api(aweme_detail)
        archive_json("douyin", "work_info", result.aweme_id, aweme_detail)
        logger.info("抖音 API 请求完成: get_work_info aweme_id=%s", result.aweme_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_work_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取作品信息失败: {e}")

    _cache_set(cache_key, result, ttl=60 * 60)
    return result


async def _fetch_comments(url: str) -> DouyinCommentsData:
    """获取作品评论（带缓存，自动解析短链）"""
    url = await _resolve_short_url(url)

    cache_key = f"dy_comments:{url}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: comments url=%s", url)
        return cached

    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_work_out_comment, auth, url)
        result = DouyinCommentsData.from_api(raw)
        archive_json("douyin", "comments", url.rstrip("/").split("/")[-1], raw if isinstance(raw, dict) else {"comments": raw})
        logger.info("抖音 API 请求完成: get_work_out_comment, 评论数=%d", len(result.comments))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_work_out_comment: %s", e)
        raise HTTPException(status_code=502, detail=f"获取评论失败: {e}")

    _cache_set(cache_key, result, ttl=120)
    return result


# ── API 端点 ──────────────────────────────────────
@router.get("/user/info", response_model=DouyinUserInfo, summary="获取抖音用户信息")
async def get_user_info(
    user_sec_id: str = Query(..., description="抖音用户 sec_uid", examples=["xxxxxx-xxxxxxxxxx"]),
):
    return await _fetch_user_info(user_sec_id)


@router.get("/user/works", response_model=list[DouyinWorkInfo], summary="获取抖音用户全部作品")
async def get_user_works(
    user_sec_id: str = Query(..., description="抖音用户 sec_uid", examples=["xxxxxx-xxxxxxxxxx"]),
):
    return await _fetch_user_works(user_sec_id)


@router.get("/work/info", response_model=DouyinWorkInfo, summary="获取抖音作品信息")
async def get_work_info(
    url: str = Query(..., description="抖音作品URL", examples=["https://www.douyin.com/video/xxxxxx"]),
):
    return await _fetch_work_info(url)


@router.get("/work/info/image", summary="获取抖音作品信息卡片图片")
async def get_work_info_image(
    url: str = Query(..., description="抖音作品URL", examples=["https://www.douyin.com/video/xxxxxx"]),
):
    work_info = await _fetch_work_info(url)
    img_bytes = render_to_bytes(work_info)
    archive_image("douyin", work_info.aweme_id, img_bytes)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/work/comments", response_model=DouyinCommentsData, summary="获取抖音作品评论")
async def get_work_comments(
    url: str = Query(..., description="抖音作品URL", examples=["https://www.douyin.com/video/xxxxxx"]),
):
    return await _fetch_comments(url)


@router.get("/work/comments/image", summary="获取抖音作品评论卡片图片")
async def get_work_comments_image(
    url: str = Query(..., description="抖音作品URL", examples=["https://www.douyin.com/video/xxxxxx"]),
    max_comments: int = Query(15, description="最多显示评论数", ge=1, le=50),
):
    comments_data = await _fetch_comments(url)
    if not comments_data.comments:
        raise HTTPException(status_code=404, detail="该作品没有可见评论")
    img_bytes = render_comments_to_bytes(comments_data, max_comments=max_comments)
    archive_image("douyin", f"{url.rstrip('/').split('/')[-1]}_comments", img_bytes)
    return Response(content=img_bytes, media_type="image/png")