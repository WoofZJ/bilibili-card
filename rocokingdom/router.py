"""
洛克王国远行商人 API 路由

端点:
  GET /rocokingdom/merchant/info         返回远行商人 JSON
  GET /rocokingdom/merchant/info/image   返回远行商人信息卡片图片
"""

import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from log import archive_image, archive_json, logger
from rocokingdom import client as rocokingdom_client
from rocokingdom.models import RocoMerchantResult
from rocokingdom.render import render_merchant_to_bytes


router = APIRouter(prefix="/rocokingdom", tags=["rocokingdom"])

_CACHE_TTL = 60
_cache: dict[str, tuple[float, RocoMerchantResult]] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: RocoMerchantResult, ttl: int = _CACHE_TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


async def _fetch_merchant() -> RocoMerchantResult:
    cache_key = "roco_merchant:default"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: rocokingdom merchant")
        return cached

    try:
        raw = await run_in_threadpool(rocokingdom_client.fetch_merchant_info)
        result = RocoMerchantResult.from_api(raw)
        archive_json("rocokingdom", "merchant", result.round_name, raw)
        logger.info("洛克王国远行商人请求完成: status=%s round=%s items=%d", result.status, result.round, len(result.items))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("洛克王国远行商人请求失败: %s", exc)
        raise HTTPException(status_code=502, detail=f"获取远行商人信息失败: {exc}") from exc

    _cache_set(cache_key, result, ttl=60)
    return result


@router.get("/merchant/info", response_model=RocoMerchantResult, summary="获取洛克王国远行商人信息")
async def get_merchant_info():
    return await _fetch_merchant()


@router.get("/merchant/info/image", summary="获取洛克王国远行商人信息卡片图片")
async def get_merchant_info_image(
    download_images: bool = Query(True, description="是否下载商品图片"),
):
    result = await _fetch_merchant()
    img_bytes = await run_in_threadpool(render_merchant_to_bytes, result, download_images)
    archive_image("rocokingdom", result.round_name, img_bytes)
    return Response(content=img_bytes, media_type="image/png")
