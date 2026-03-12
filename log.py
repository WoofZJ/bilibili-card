"""
日志模块 — 统一管理应用日志与请求数据归档

目录结构:
  logs/
    app.log              ← 主日志文件 (自动轮转, 单文件 5MB, 保留 5 份)
    archive/
      video_info/        ← 视频信息 JSON 归档 (缓存未命中时)
      comments/          ← 评论 JSON 归档 (缓存未命中时)
      image/             ← 渲染图片归档 (缓存未命中时)
"""

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── 目录初始化 ────────────────────────────────────
_LOG_DIR = Path(__file__).parent / "logs"
_ARCHIVE_DIR = _LOG_DIR / "archive"

for _sub in ("video_info", "comments", "image"):
    (_ARCHIVE_DIR / _sub).mkdir(parents=True, exist_ok=True)

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


def archive_json(category: str, name: str, data: dict) -> Path:
    """归档 JSON 到 logs/archive/{category}/{name}_{timestamp}.json

    Args:
        category: 子目录名, 如 "video_info" / "comments"
        name: 文件名前缀, 通常为 bvid
        data: 要序列化的字典
    Returns:
        写入的文件路径
    """
    dest = _ARCHIVE_DIR / category / f"{name}_{_timestamp()}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug("JSON 已归档 → %s", dest)
    return dest


def archive_image(name: str, img_bytes: bytes) -> Path:
    """归档图片到 logs/archive/image/{name}_{timestamp}.png

    Args:
        name: 文件名前缀, 通常为 bvid 或 bvid_comments
        img_bytes: PNG 图片字节
    Returns:
        写入的文件路径
    """
    dest = _ARCHIVE_DIR / "image" / f"{name}_{_timestamp()}.png"
    with open(dest, "wb") as f:
        f.write(img_bytes)
    logger.debug("图片已归档 → %s", dest)
    return dest
