"""
网易云音乐信息 API 路由

端点:
  GET  /song/info?song_id=xxx  根据歌曲ID返回歌曲 JSON（含下载链接和歌词）
  GET  /song/info?url=xxx      根据网易云歌曲链接返回歌曲 JSON（含下载链接和歌词）
  GET  /song/resolve?url=xxx   从网易云歌曲链接解析歌曲ID
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from log import archive_json, logger
from neteasecloud import client as netease_client
from neteasecloud.models import NeteaseDownloadInfo, NeteaseLyricInfo, NeteaseSongInfo


router = APIRouter(prefix="/neteasecloud", tags=["neteasecloud"])


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
    entry = _cache.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


async def _resolve_song_id(
    song_id: str | None = None,
    id_: str | None = None,
    url: str | None = None,
) -> int:
    source = song_id or id_ or url
    if not source:
        raise HTTPException(status_code=400, detail="必须提供 song_id、id 或 url 参数")

    try:
        return await run_in_threadpool(netease_client.extract_song_id, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except netease_client.NeteaseClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── 业务逻辑 ─────────────────────────────────────
async def _fetch_download_info(
    song_id: int,
    quality: str,
) -> tuple[NeteaseDownloadInfo | None, str]:
    try:
        raw = await run_in_threadpool(netease_client.fetch_song_url, song_id, quality)
        archive_json("neteasecloud", "song_url", f"{song_id}_{quality}", raw)
    except netease_client.NeteaseClientError as exc:
        logger.warning("网易云歌曲链接获取失败: song_id=%s quality=%s: %s", song_id, quality, exc)
        return None, str(exc)
    except Exception as exc:
        logger.warning("网易云歌曲链接获取异常: song_id=%s quality=%s: %s", song_id, quality, exc)
        return None, str(exc)

    download = NeteaseDownloadInfo.from_api(raw, requested_level=quality)
    if not download.available:
        return download, "获取音乐URL失败，可能是版权限制或音质不支持"
    return download, ""


async def _fetch_lyric_info(song_id: int) -> tuple[NeteaseLyricInfo, str]:
    try:
        raw = await run_in_threadpool(netease_client.fetch_lyric, song_id)
        archive_json("neteasecloud", "lyric", str(song_id), raw)
    except netease_client.NeteaseClientError as exc:
        logger.warning("网易云歌词获取失败: song_id=%s: %s", song_id, exc)
        return NeteaseLyricInfo(), str(exc)
    except Exception as exc:
        logger.warning("网易云歌词获取异常: song_id=%s: %s", song_id, exc)
        return NeteaseLyricInfo(), str(exc)

    return NeteaseLyricInfo.from_api(raw), ""


async def _fetch_song_info(song_id: int, quality: str = "lossless") -> NeteaseSongInfo:
    cache_key = f"netease_song:{song_id}:{quality}"
    if cached := _cache_get(cache_key):
        logger.info("缓存命中: netease song_id=%s quality=%s", song_id, quality)
        return cached

    try:
        raw = await run_in_threadpool(netease_client.fetch_song_detail, song_id)
        archive_json("neteasecloud", "song_info", str(song_id), raw)
        logger.info("网易云 API 请求完成: get_song_detail song_id=%s", song_id)
    except netease_client.NeteaseClientError as exc:
        logger.error("网易云 API 请求失败: get_song_detail song_id=%s: %s", song_id, exc)
        raise HTTPException(status_code=502, detail=f"获取歌曲信息失败: {exc}") from exc
    except Exception as exc:
        logger.error("网易云歌曲信息获取异常: song_id=%s: %s", song_id, exc)
        raise HTTPException(status_code=502, detail=f"获取歌曲信息失败: {exc}") from exc

    try:
        result = NeteaseSongInfo.from_api(raw)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"歌曲 {song_id} 不存在或无可见信息") from exc

    download_result, lyric_result = await asyncio.gather(
        _fetch_download_info(song_id, quality),
        _fetch_lyric_info(song_id),
    )

    download, download_error = download_result
    lyrics, lyric_error = lyric_result

    result.download = download
    result.lyrics = lyrics
    result.download_error = download_error
    result.lyric_error = lyric_error

    if download:
        result.url = download.url
        result.level = download.level
        result.size = download.size_formatted
    else:
        result.level = quality
        result.size = "获取失败"

    result.lyric = lyrics.lyric
    result.tlyric = lyrics.translated_lyric

    _cache_set(cache_key, result, ttl=60 * 60)
    return result


# ── API 端点 ──────────────────────────────────────
@router.get("/song/info", response_model=NeteaseSongInfo, summary="根据歌曲ID或URL获取网易云歌曲信息")
async def get_song_info(
    request: Request,
    song_id: str | None = Query(None, description="网易云歌曲ID", examples=["2621930495"]),
    url: str | None = Query(
        None,
        description="网易云歌曲链接，支持 music.163.com 或 163cn.tv 短链接",
        examples=["https://music.163.com/#/song?id=2621930495"],
    ),
    quality: str = Query(
        "lossless",
        description="播放/下载链接音质，默认 lossless 通常返回 flac",
        examples=["lossless"],
    ),
    id_: str | None = Query(None, alias="id", include_in_schema=False),
):
    _enforce_rate_limit(request, "netease/song/info")
    if quality not in netease_client.VALID_QUALITY_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"无效的音质参数，支持: {', '.join(sorted(netease_client.VALID_QUALITY_LEVELS))}",
        )
    resolved_song_id = await _resolve_song_id(song_id=song_id, id_=id_, url=url)
    logger.info(
        "收到请求: /neteasecloud/song/info song_id=%s quality=%s",
        resolved_song_id,
        quality,
    )
    return await _fetch_song_info(resolved_song_id, quality=quality)


@router.get("/song/resolve", summary="从网易云歌曲链接解析歌曲ID")
async def resolve_song_url(
    request: Request,
    url: str = Query(..., description="网易云歌曲链接", examples=["https://music.163.com/#/song?id=2621930495"]),
):
    _enforce_rate_limit(request, "netease/song/resolve")
    try:
        song_id = await run_in_threadpool(netease_client.extract_song_id, url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except netease_client.NeteaseClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"song_id": song_id}
