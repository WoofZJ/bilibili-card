"""
抖音数据 API 路由

端点:
  GET  /user/info?user_sec_id=xxx         获取用户信息
  GET  /user/works?user_sec_id=xxx        获取用户全部作品
  GET  /work/info?work_id=xxx             获取作品信息
  GET  /work/comments?work_id=xxx         获取作品评论
  GET  /search/user?keyword=xxx           搜索用户
  GET  /search/work?keyword=xxx           搜索作品
"""

import asyncio
from functools import partial

from fastapi import APIRouter, Query, HTTPException

from log import logger
from douyin.models import DouyinUserInfo, DouyinWorkInfo

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


# ── API 端点 ──────────────────────────────────────
@router.get("/user/info", response_model=DouyinUserInfo, summary="获取抖音用户信息")
async def get_user_info(
    user_sec_id: str = Query(..., description="抖音用户主页URL", examples=["xxxxxx-xxxxxxxxxx"]),
):
    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_user_info, auth, f"https://www.douyin.com/user/{user_sec_id}")
        result = DouyinUserInfo.from_api(raw)
        logger.info("抖音 API 请求完成: get_user_info nickname=%s", result.nickname)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_user_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取用户信息失败: {e}")


@router.get("/user/works", response_model=list[DouyinWorkInfo], summary="获取抖音用户全部作品")
async def get_user_works(
    user_sec_id: str = Query(..., description="抖音用户主页URL", examples=["xxxxxx-xxxxxxxxxx"]),
):
    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_user_all_work_info, auth, user_sec_id)
        result = DouyinWorkInfo.from_api_list(raw)
        logger.info("抖音 API 请求完成: get_user_all_work_info, 作品数=%d", len(result))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_user_all_work_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取用户作品失败: {e}")


@router.get("/work/info", response_model=DouyinWorkInfo, summary="获取抖音作品信息")
async def get_work_info(
    work_id: str = Query(..., description="抖音作品ID", examples=["xxxxxx-xxxxxxxxxx"]),
):
    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        raw = await _run_sync(DouyinAPI.get_work_info, auth, work_id)
        aweme_detail = raw.get("aweme_detail", raw)
        result = DouyinWorkInfo.from_api(aweme_detail)
        logger.info("抖音 API 请求完成: get_work_info aweme_id=%s", result.aweme_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("抖音 API 请求失败: get_work_info: %s", e)
        raise HTTPException(status_code=502, detail=f"获取作品信息失败: {e}")


@router.get("/work/comments", summary="获取抖音作品全部评论")
async def get_work_comments(
    work_id: str = Query(..., description="抖音作品ID", examples=["xxxxxx-xxxxxxxxxx"]),
):
    from douyin.dy_apis.douyin_api import DouyinAPI
    auth = _get_auth()
    try:
        result = await _run_sync(DouyinAPI.get_work_all_comment, auth, work_id)
        logger.info("抖音 API 请求完成: get_work_all_comment, 评论数=%d", len(result))
        return result
    except Exception as e:
        logger.error("抖音 API 请求失败: get_work_all_comment: %s", e)
        raise HTTPException(status_code=502, detail=f"获取评论失败: {e}")