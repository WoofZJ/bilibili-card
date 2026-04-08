"""
日志模块 — 统一管理应用日志与请求数据归档

目录结构:
  logs/
    app.log              ← 主日志文件 (自动轮转, 单文件 5MB, 保留 5 份)
    archive/
      bilibili/
        video_info/      ← B站视频信息 JSON 归档
        comments/        ← B站评论 JSON 归档
        image/           ← B站渲染图片归档
      douyin/
        work_info/       ← 抖音作品信息 JSON 归档
        comments/        ← 抖音评论 JSON 归档
        image/           ← 抖音渲染图片归档
"""

import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── 目录初始化 ────────────────────────────────────
_LOG_DIR = Path(__file__).parent / "logs"
_ARCHIVE_DIR = _LOG_DIR / "archive"

for _platform, _subs in (
    ("bilibili", ("video_info", "comments", "image")),
    ("douyin", ("work_info", "comments", "image")),
    ("youtube", ("video_info", "comments", "image")),
):
    for _sub in _subs:
        (_ARCHIVE_DIR / _platform / _sub).mkdir(parents=True, exist_ok=True)

# ── Logger 配置 ───────────────────────────────────
logger = logging.getLogger("bilibili_api")
logger.setLevel(logging.DEBUG)

_FMT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 文件: DEBUG 及以上, 自动轮转
_fh = RotatingFileHandler(
    _LOG_DIR / "app.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_FMT)

# 控制台: INFO 及以上
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
))

logger.addHandler(_fh)
logger.addHandler(_ch)


# ── 归档工具 ──────────────────────────────────────
def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def archive_json(platform: str, category: str, name: str, data: dict) -> Path:
    """归档 JSON 到 logs/archive/{platform}/{category}/{name}.json

    Args:
        platform: 平台名, 如 "bilibili" / "douyin"
        category: 子目录名, 如 "video_info" / "comments"
        name: 文件名前缀, 通常为 bvid 或 aweme_id
        data: 要序列化的字典
    Returns:
        写入的文件路径
    """
    dest = _ARCHIVE_DIR / platform / category / f"{name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug("JSON 已归档 → %s", dest)
    return dest


def archive_image(platform: str, name: str, img_bytes: bytes) -> Path:
    """归档图片到 logs/archive/{platform}/image/{name}.png

    Args:
        platform: 平台名, 如 "bilibili" / "douyin"
        name: 文件名前缀, 通常为 bvid 或 aweme_id
        img_bytes: PNG 图片字节
    Returns:
        写入的文件路径
    """
    dest = _ARCHIVE_DIR / platform / "image" / f"{name}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(img_bytes)
    logger.debug("图片已归档 → %s", dest)
    return dest
