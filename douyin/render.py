import io
import re
import requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from douyin.models import DouyinWorkInfo, DouyinCommentsData, DouyinCommentItem

# ── 常量 ──────────────────────────────────────────
CARD_WIDTH = 800
CARD_HEIGHT_BASE = 680
COVER_HEIGHT = 450  # 800 / 16 * 9
PADDING = 16
LINE_GAP = 10
CARD_BG = (255, 255, 255)
AVATAR_SIZE = 60

COLOR_TITLE = (30, 30, 30)
COLOR_SUB = (102, 102, 102)
COLOR_ACCENT = (254, 44, 85)  # 抖音红
COLOR_DESC_TEXT = (153, 153, 153)
COLOR_STAT_LABEL = (153, 153, 153)
COLOR_STAT_VALUE = (51, 51, 51)
COLOR_DURATION_BG = (0, 0, 0, 180)
COLOR_DURATION_TEXT = (255, 255, 255)
COLOR_DIVIDER = (240, 240, 240)

# ── 字体加载 ─────────────────────────────────────
_ASSETS_DIR = Path(__file__).parent.parent / "assets"

_MAIN_FONT_PATH = _ASSETS_DIR / "LXGWWenKaiMono-Regular.ttf"
_EMOJI_FONT_PATH = _ASSETS_DIR / "seguiemj.ttf"
_FALLBACK_FONT_PATH = _ASSETS_DIR / "tahoma.ttf"

# ── emoji 正则 ────────────────────────────────────
_EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50"
    "\U000023F0-\U000023FF"
    "\U0000203C\U00002049"
    "\U0000231A\U0000231B"
    "\U00002328"
    "\U000023CF"
    "\U000023E9-\U000023F3"
    "\U000023F8-\U000023FA"
    "\U00002934\U00002935"
    "\U000025AA\U000025AB"
    "\U000025B6\U000025C0"
    "\U000025FB-\U000025FE"
    "\U00002614\U00002615"
    "\U00002648-\U00002653"
    "\U0000267F"
    "\U00002693"
    "\U000026A1"
    "\U000026AA\U000026AB"
    "\U000026BD\U000026BE"
    "\U000026C4\U000026C5"
    "\U000026CE\U000026CF"
    "\U000026D4"
    "\U000026EA"
    "\U000026F2\U000026F3"
    "\U000026F5"
    "\U000026FA"
    "\U000026FD"
    "\U00002702"
    "\U00002705"
    "\U00002708-\U0000270D"
    "\U0000270F"
    "\U00002712"
    "\U00002714"
    "\U00002716"
    "\U0000271D"
    "\U00002721"
    "\U00002733\U00002734"
    "\U00002744"
    "\U00002747"
    "\U0000274C"
    "\U0000274E"
    "\U00002753-\U00002755"
    "\U00002757"
    "\U00002763\U00002764"
    "\U00002795-\U00002797"
    "\U000027A1"
    "\U000027B0"
    "\U000027BF"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_MAIN_FONT_PATH), size)
    except (OSError, IOError):
        return ImageFont.load_default()


FONT_TITLE = _find_font(32, bold=True)
FONT_BODY = _find_font(24)
FONT_SMALL = _find_font(20)
FONT_DURATION = _find_font(22, bold=True)
FONT_STAT_VALUE = _find_font(26, bold=True)
FONT_STAT_LABEL = _find_font(18)

# emoji 字体
try:
    _EMOJI_FONT = ImageFont.truetype(str(_EMOJI_FONT_PATH), 24)
except (OSError, IOError):
    _EMOJI_FONT = FONT_BODY


# ── 通用绘图工具 ─────────────────────────────────

def _rounded_rectangle(draw: ImageDraw.ImageDraw, box, radius: int, fill):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_text_with_fallback(draw: ImageDraw.ImageDraw, xy, text: str, fill, font, canvas=None):
    """绘制文本，自动处理 emoji 回退"""
    x, y = xy
    for ch in text:
        if _EMOJI_PATTERN.match(ch):
            try:
                draw.text((x, y), ch, fill=fill, font=_EMOJI_FONT, embedded_color=True)
                x += int(_EMOJI_FONT.getlength(ch))
            except Exception:
                draw.text((x, y), ch, fill=fill, font=font)
                x += int(font.getlength(ch))
        else:
            draw.text((x, y), ch, fill=fill, font=font)
            x += int(font.getlength(ch))


def _truncate_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    for i in range(len(text), 0, -1):
        if font.getlength(text[:i] + "...") <= max_width:
            return text[:i] + "..."
    return "..."


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 5) -> list[str]:
    lines = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                break
            continue
        test = current + ch
        if font.getlength(test) > max_width:
            lines.append(current)
            current = ch
            if len(lines) >= max_lines:
                break
        else:
            current = test
    if current and len(lines) < max_lines:
        lines.append(current)
    elif current and len(lines) >= max_lines:
        if lines:
            lines[-1] = _truncate_text(lines[-1], font, max_width)
    return lines or [""]


def _draw_stat_item(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, label: str, value: str):
    val_w = FONT_STAT_VALUE.getlength(value)
    val_x = x + (width - val_w) / 2
    draw.text((val_x, y), value, fill=COLOR_STAT_VALUE, font=FONT_STAT_VALUE)
    lbl_w = FONT_STAT_LABEL.getlength(label)
    lbl_x = x + (width - lbl_w) / 2
    draw.text((lbl_x, y + 36), label, fill=COLOR_STAT_LABEL, font=FONT_STAT_LABEL)


# ── 图片加载 ─────────────────────────────────────

def _load_cover(url: str) -> Image.Image:
    """从 URL 加载封面图片并裁剪为 16:9"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        # 裁剪为 16:9
        w, h = img.size
        target_ratio = CARD_WIDTH / COVER_HEIGHT
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        return img.resize((CARD_WIDTH, COVER_HEIGHT), Image.Resampling.LANCZOS)
    except Exception:
        return _create_placeholder_cover()


def _create_placeholder_cover() -> Image.Image:
    img = Image.new("RGBA", (CARD_WIDTH, COVER_HEIGHT), (200, 200, 200, 255))
    draw = ImageDraw.Draw(img)
    text = "暂无封面"
    tw = FONT_TITLE.getlength(text)
    draw.text(((CARD_WIDTH - tw) / 2, COVER_HEIGHT / 2 - 20), text, fill=(150, 150, 150), font=FONT_TITLE)
    return img


def _load_avatar(url: str, size: int) -> Image.Image | None:
    """加载头像并裁剪为圆形"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        # 圆形蒙版
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask)
        return output
    except Exception:
        return None


def _create_placeholder_avatar(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(200, 200, 200, 255))
    return img


def _load_sticker(url: str, max_size: int = 120) -> Image.Image | None:
    """加载评论贴纸"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        w, h = img.size
        scale = min(max_size / w, max_size / h, 1.0)
        new_w, new_h = int(w * scale), int(h * scale)
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception:
        return None


def _draw_logo(image: Image.Image, logo_path: str, x: int, y: int, height: int) -> int:
    try:
        logo = Image.open(logo_path).convert("RGBA")
        w, h = logo.size
        scale = height / h
        new_w = int(w * scale)
        logo = logo.resize((new_w, height), Image.Resampling.LANCZOS)
        image.paste(logo, (x, y), logo)
        return new_w
    except Exception:
        return 0


def _draw_copyright(draw: ImageDraw.ImageDraw, canvas: Image.Image, x: int, y: int):
    text = "Made by"
    draw.text((x, y), text, fill=COLOR_STAT_LABEL, font=FONT_SMALL)
    text_w = FONT_SMALL.getlength(text)
    x += int(text_w) + 5
    logo_w = _draw_logo(canvas, str(_ASSETS_DIR / "logo.png"), x, y - 2, 32)
    text = "WoofZJ"
    x += logo_w + 5
    draw.text((x, y), text, fill=(255, 0, 0), font=FONT_SMALL)


# ── 视频卡片渲染 ─────────────────────────────────

def render_work_card(work: DouyinWorkInfo, download_cover: bool = True) -> Image.Image:
    """
    将 DouyinWorkInfo 渲染为卡片图片

    Args:
        work: 作品信息
        download_cover: 是否下载封面图片

    Returns:
        PIL.Image.Image 对象
    """
    content_width = CARD_WIDTH - PADDING * 2

    title_lines = _wrap_text(work.desc, FONT_TITLE, content_width, max_lines=5)
    title_line_height = 48
    title_height = len(title_lines) * title_line_height
    total_height = CARD_HEIGHT_BASE + title_height

    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), (0, 0, 0, 0))

    # 背景
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, CARD_WIDTH, total_height), fill=(255, 255, 255))

    # 封面
    if download_cover and work.cover:
        cover = _load_cover(work.cover)
    else:
        cover = _create_placeholder_cover()
    cover_rgba = cover.convert("RGBA")
    canvas.paste(cover_rgba, (0, 0), cover_rgba)

    # 时长标签（仅视频类型）
    if work.duration > 0:
        dur_text = work.duration_str
        dur_bbox = FONT_DURATION.getbbox(dur_text)
        dur_tw = dur_bbox[2] - dur_bbox[0]
        dur_th = dur_bbox[3] - dur_bbox[1]
        dur_pad_x, dur_pad_y = 12, 6
        dur_x = CARD_WIDTH - dur_tw - dur_pad_x * 2 - 16
        dur_y = COVER_HEIGHT - dur_th - dur_pad_y * 2 - 16
        dur_overlay = Image.new("RGBA", (dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), (0, 0, 0, 0))
        dur_draw = ImageDraw.Draw(dur_overlay)
        dur_draw.rectangle((0, 0, dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), fill=COLOR_DURATION_BG)
        canvas.paste(dur_overlay, (dur_x, dur_y), dur_overlay)
        draw.text((dur_x + dur_pad_x, dur_y + dur_pad_y - 5), dur_text, fill=COLOR_DURATION_TEXT, font=FONT_DURATION)

    # 标题（作品描述）
    y_cursor = COVER_HEIGHT + LINE_GAP
    for line in title_lines:
        _draw_text_with_fallback(draw, (PADDING, y_cursor), line, fill=COLOR_TITLE, font=FONT_TITLE, canvas=canvas)
        y_cursor += title_line_height

    y_cursor += LINE_GAP

    # 作者信息
    avatar = None
    if download_cover and work.author_avatar:
        avatar = _load_avatar(work.author_avatar, AVATAR_SIZE)
    if not avatar:
        avatar = _create_placeholder_avatar(AVATAR_SIZE)
    canvas.paste(avatar, (PADDING, y_cursor), avatar)
    author_text = work.author_nickname
    text_y = y_cursor + (AVATAR_SIZE - FONT_BODY.size) // 2
    draw.text((PADDING + AVATAR_SIZE + PADDING, text_y), author_text, fill=COLOR_ACCENT, font=FONT_BODY)
    y_cursor += AVATAR_SIZE + LINE_GAP

    # 发布时间、分辨率
    meta_parts = []
    if work.create_time:
        meta_parts.append(f"发布于 {work.create_time_str}")
    if work.width and work.height:
        meta_parts.append(f"分辨率：{work.resolution_str}")
    if work.music_title:
        meta_parts.append(f"♪ {work.music_title}")
    meta_text = " | ".join(meta_parts)
    draw.text((PADDING, y_cursor), meta_text, fill=COLOR_DESC_TEXT, font=FONT_SMALL)
    y_cursor += FONT_SMALL.size + LINE_GAP + 4

    # 分隔线
    draw.line((PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor), fill=COLOR_DIVIDER, width=2)
    y_cursor += LINE_GAP + 4

    # 数据截止时间
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot_text = f"截止于 {snapshot_time} 的数据："
    snapshot_w = FONT_SMALL.getlength(snapshot_text)
    draw.text(((CARD_WIDTH - snapshot_w) / 2, y_cursor), snapshot_text, fill=COLOR_DESC_TEXT, font=FONT_SMALL)
    y_cursor += FONT_SMALL.size + LINE_GAP

    # 数据统计
    stats = [
        ("点赞", DouyinWorkInfo.format_count(work.digg_count)),
        ("评论", DouyinWorkInfo.format_count(work.comment_count)),
        ("收藏", DouyinWorkInfo.format_count(work.collect_count)),
        ("分享", DouyinWorkInfo.format_count(work.share_count)),
    ]
    if work.play_count > 0:
        stats.insert(0, ("播放", DouyinWorkInfo.format_count(work.play_count)))
    item_width = content_width // len(stats)
    x = PADDING
    for label, value in stats:
        _draw_stat_item(draw, x, y_cursor, item_width, label, value)
        x += item_width
    y_cursor += 80

    _draw_copyright(draw, canvas, CARD_WIDTH // 2 - 100, y_cursor)

    return canvas.convert("RGB")


def render_to_bytes(work: DouyinWorkInfo, fmt: str = "PNG", download_cover: bool = True) -> bytes:
    """渲染并返回图片字节数据"""
    img = render_work_card(work, download_cover=download_cover)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()


# ── 评论区常量 ────────────────────────────────────
COMMENT_CARD_WIDTH = 800
COMMENT_PADDING = 20
COMMENT_AVATAR_SIZE = 48
COMMENT_SUB_AVATAR_SIZE = 36
COLOR_COMMENT_BG = (255, 255, 255)
COLOR_COMMENT_HEADER_BG = (254, 44, 85)  # 抖音红
COLOR_COMMENT_HEADER_TEXT = (255, 255, 255)
COLOR_HOT_BADGE_BG = (255, 68, 68)
COLOR_HOT_BADGE_TEXT = (255, 255, 255)
COLOR_AUTHOR_LIKED_BG = (254, 44, 85)
COLOR_AUTHOR_LIKED_TEXT = (255, 255, 255)
COLOR_LIKE_TEXT = (153, 153, 153)
COLOR_TIME_TEXT = (153, 153, 153)
COLOR_REPLY_COUNT = (109, 192, 233)
COLOR_USERNAME = (51, 51, 51)
COLOR_MESSAGE = (34, 34, 34)
COLOR_SUB_LINE = (229, 233, 239)
COLOR_IP_TEXT = (180, 180, 180)

# 评论区字体
FONT_COMMENT_HEADER = _find_font(24, bold=True)
FONT_COMMENT_USERNAME = _find_font(24, bold=True)
FONT_COMMENT_MESSAGE = _find_font(24)
FONT_COMMENT_META = _find_font(20)
FONT_COMMENT_BADGE = _find_font(18, bold=True)
FONT_COMMENT_SUB_USERNAME = _find_font(22, bold=True)
FONT_COMMENT_SUB_MESSAGE = _find_font(22)
FONT_COMMENT_SUB_META = _find_font(18)


def _draw_small_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, bg_color, text_color) -> int:
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 3
    _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), 4, bg_color)
    draw.text((x + pad_x, y + pad_y - 2), text, fill=text_color, font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _measure_comment_height(comment: DouyinCommentItem, content_width: int, is_sub: bool = False) -> int:
    """预计算单条评论所需高度"""
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE

    name_line_h = 28 if is_sub else 30

    text_left = avatar_size + 12
    text_width = content_width - text_left

    # 消息行
    msg_line_h = 30 if is_sub else 32
    msg_lines = _wrap_text(comment.text, font_msg, text_width, max_lines=6)
    msg_h = len(msg_lines) * msg_line_h

    # 贴纸高度
    sticker_h = 0
    if comment.sticker_url and not is_sub:
        sticker_h = 120 + 8  # max_size + padding

    # meta 行（点赞、时间）
    meta_h = 28 if is_sub else 30

    h = name_line_h + 6 + msg_h + sticker_h + 8 + meta_h + 12
    return max(h, avatar_size + 16)


def _draw_single_comment(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    comment: DouyinCommentItem,
    x: int,
    y: int,
    content_width: int,
    is_sub: bool = False,
) -> int:
    """绘制单条评论，返回占用的高度"""
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE
    font_username = FONT_COMMENT_SUB_USERNAME if is_sub else FONT_COMMENT_USERNAME
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    font_meta = FONT_COMMENT_SUB_META if is_sub else FONT_COMMENT_META

    start_y = y

    # 头像
    avatar = _load_avatar(comment.avatar, avatar_size)
    if avatar is None:
        avatar = _create_placeholder_avatar(avatar_size)
    canvas.paste(avatar, (x, y), avatar)

    text_x = x + avatar_size + 12
    text_width = content_width - avatar_size - 12

    # 用户名行: [热评] [作者赞] 用户名
    name_y = y + 2
    badge_x = text_x

    if comment.is_hot:
        w = _draw_small_badge(draw, badge_x, name_y, "热评", COLOR_HOT_BADGE_BG, COLOR_HOT_BADGE_TEXT)
        badge_x += w + 6

    if comment.is_author_digged:
        w = _draw_small_badge(draw, badge_x, name_y, "作者赞", COLOR_AUTHOR_LIKED_BG, COLOR_AUTHOR_LIKED_TEXT)
        badge_x += w + 6

    uname_display = _truncate_text(comment.nickname, font_username, text_width - (badge_x - text_x) - 60)
    draw.text((badge_x, name_y), uname_display, fill=COLOR_USERNAME, font=font_username)

    name_line_h = 28 if is_sub else 30
    y += name_line_h + 6

    # 评论内容
    msg_line_h = 30 if is_sub else 32
    msg_lines = _wrap_text(comment.text, font_msg, text_width, max_lines=6)
    for line in msg_lines:
        _draw_text_with_fallback(draw, (text_x, y), line, fill=COLOR_MESSAGE, font=font_msg, canvas=canvas)
        y += msg_line_h

    # 贴纸
    if comment.sticker_url and not is_sub:
        sticker = _load_sticker(comment.sticker_url)
        if sticker:
            canvas.paste(sticker, (text_x, y), sticker)
            y += sticker.size[1] + 8

    y += 8

    # 底部 meta: 点赞数  时间  IP属地  回复数
    meta_x = text_x

    like_text = f"♥ {comment.digg_count}"
    draw.text((meta_x, y), like_text, fill=COLOR_LIKE_TEXT, font=font_meta)
    meta_x += int(font_meta.getlength(like_text)) + 20

    time_text = comment.create_time_str
    if time_text:
        draw.text((meta_x, y), time_text, fill=COLOR_TIME_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(time_text)) + 20

    if comment.ip_label:
        ip_text = f"IP: {comment.ip_label}"
        draw.text((meta_x, y), ip_text, fill=COLOR_IP_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(ip_text)) + 20

    if comment.reply_comment_total > 0 and not is_sub:
        reply_text = f"{comment.reply_comment_total}条回复"
        draw.text((meta_x, y), reply_text, fill=COLOR_REPLY_COUNT, font=font_meta)

    meta_h = 28 if is_sub else 30
    y += meta_h + 12

    return y - start_y


def render_comments_card(comments_data: DouyinCommentsData, max_comments: int = 15) -> Image.Image:
    """
    将评论数据渲染为卡片图片

    Args:
        comments_data: 评论数据
        max_comments: 最多显示的评论数量

    Returns:
        PIL.Image.Image 对象
    """
    content_width = COMMENT_CARD_WIDTH - COMMENT_PADDING * 2

    # 第一轮：计算总高度
    header_h = 50

    display_comments = comments_data.comments[:max_comments]

    total_h = header_h + COMMENT_PADDING
    for comment in display_comments:
        total_h += _measure_comment_height(comment, content_width)
        for sub in comment.sub_comments:
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12
            total_h += _measure_comment_height(sub, sub_width, is_sub=True)
        total_h += 12

    # 创建画布
    canvas = Image.new("RGBA", (COMMENT_CARD_WIDTH, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, total_h), 0, (255, 255, 255, 255))

    # 头部
    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, header_h), 0, COLOR_COMMENT_HEADER_BG)
    header_text = f"热门评论 ({comments_data.total})"
    header_tw = FONT_COMMENT_HEADER.getlength(header_text)
    height = FONT_COMMENT_HEADER.getbbox(header_text)[3]
    draw.text(
        ((COMMENT_CARD_WIDTH - header_tw) / 2, (header_h - height) / 2),
        header_text,
        fill=COLOR_COMMENT_HEADER_TEXT,
        font=FONT_COMMENT_HEADER,
    )

    y_cursor = header_h + COMMENT_PADDING

    # 逐条绘制评论
    for idx, comment in enumerate(display_comments):
        h = _draw_single_comment(canvas, draw, comment, COMMENT_PADDING, y_cursor, content_width)
        y_cursor += h

        # 子评论
        if comment.sub_comments:
            sub_x = COMMENT_PADDING + COMMENT_AVATAR_SIZE + 12
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12

            line_x = sub_x - 6
            sub_start_y = y_cursor

            for sub in comment.sub_comments:
                sub_h = _draw_single_comment(canvas, draw, sub, sub_x, y_cursor, sub_width, is_sub=True)
                y_cursor += sub_h

            draw.line(
                (line_x, sub_start_y, line_x, y_cursor - 16),
                fill=COLOR_SUB_LINE,
                width=2,
            )

        # 分隔线
        if idx < len(display_comments) - 1:
            draw.line(
                (COMMENT_PADDING, y_cursor, COMMENT_CARD_WIDTH - COMMENT_PADDING, y_cursor),
                fill=COLOR_DIVIDER,
                width=1,
            )
            y_cursor += 12

    y_cursor -= 18
    _draw_copyright(draw, canvas, COMMENT_CARD_WIDTH // 2 - 100, y_cursor)
    y_cursor += 30

    actual_h = y_cursor
    if actual_h < total_h:
        canvas = canvas.crop((0, 0, COMMENT_CARD_WIDTH, actual_h))

    return canvas.convert("RGB")


def render_comments_to_bytes(comments_data: DouyinCommentsData, fmt: str = "PNG", max_comments: int = 15) -> bytes:
    """渲染评论卡片并返回图片字节数据"""
    img = render_comments_card(comments_data, max_comments=max_comments)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()
