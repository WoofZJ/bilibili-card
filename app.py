"""
信息卡片 Web API — 统一入口

启动: uvicorn app:app --reload --host 0.0.0.0 --port 8000

API 路由:
  /bilibili/...   B站相关接口 (详见 bilibili/router.py)
  /douyin/...     抖音相关接口 (详见 douyin/router.py)
  /rocokingdom/... 洛克王国相关接口 (详见 rocokingdom/router.py)
  /xiaoheihe/...   小黑盒相关接口 (详见 xiaoheihe/router.py)
  /health         健康检查
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from log import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化各平台客户端"""
    # ── 初始化 B站 客户端 ──
    from bilibili_api import request_settings, select_client
    request_settings.set("impersonate", "safari")
    select_client("curl_cffi")
    logger.info("bilibili_api 客户端已初始化")

    try:
        yield
    finally:
        from douyin.router import shutdown_client as shutdown_douyin_client
        await shutdown_douyin_client()


app = FastAPI(
    title="信息卡片 API",
    description="聚合 B站 / 抖音 / YouTube / 小黑盒 / 洛克王国 数据，支持 JSON 和卡片图片输出",
    version="2.0.0",
    lifespan=lifespan,
)

# ── 注册路由 ──────────────────────────────────────
from bilibili.router import router as bilibili_router
from douyin.router import router as douyin_router
from rocokingdom.router import router as rocokingdom_router
from youtube.router import router as youtube_router
from xiaoheihe.router import router as xiaoheihe_router

app.include_router(bilibili_router)
app.include_router(douyin_router)
app.include_router(rocokingdom_router)
app.include_router(youtube_router)
app.include_router(xiaoheihe_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
