import io
import re
import requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from youtube.models import YouTubeVideoInfo, YouTubeCommentItem, YouTubeCommentsData, language_name

# ── 常量 ──────────────────────────────────────────
CARD_WIDTH = 800
CARD_HEIGHT_BASE = 730
COVER_HEIGHT = 450  # 800 / 16 * 9
PADDING = 16
LINE_GAP = 10
CARD_BG = (255, 255, 255)
AVATAR_SIZE = 60

COLOR_TITLE = (30, 30, 30)
COLOR_SUB = (102, 102, 102)
COLOR_ACCENT = (0xFF, 0x00, 0x00)  # YouTube 红
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
_FALLBACK_FONT_PATH = _ASSETS_DIR / "unifont.otf"


class FontConfig:
    def __init__(self, size: int):
        self.main = ImageFont.truetype(str(_MAIN_FONT_PATH), size)
        try:
            self.emoji = ImageFont.truetype(str(_EMOJI_FONT_PATH), size)
        except (OSError, IOError):
            self.emoji = self.main
        try:
            self.fallback = ImageFont.truetype(str(_FALLBACK_FONT_PATH), size)
        except (OSError, IOError):
            self.fallback = self.main


_font_config_cache: dict[int, FontConfig] = {}


def _get_font_config(size: int) -> FontConfig:
    if size not in _font_config_cache:
        _font_config_cache[size] = FontConfig(size)
    return _font_config_cache[size]


_NOTDEF_REF: dict[tuple, bytes] = {}


def _is_tofu(char: str, font: ImageFont.FreeTypeFont) -> bool:
    key = (int(font.size), *font.getname())
    if key not in _NOTDEF_REF:
        _NOTDEF_REF[key] = bytes(font.getmask(chr(0xFFFE)))
    return bytes(font.getmask(char)) == _NOTDEF_REF[key]


# ── Emoji 正则 ──
_EMOJI_BASE_CHARS = (
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000203C\U00002049"
    "\U00002139\U00002328"
    "\U0000231A\U0000231B"
    "\U000023CF"
    "\U000023E9-\U000023F3"
    "\U000023F8-\U000023FA"
    "\U000024C2"
    "\U000025AA\U000025AB\U000025B6\U000025C0"
    "\U000025FB-\U000025FE"
    "\U00002934\U00002935"
    "\U00002B05-\U00002B07"
    "\U00002B1B\U00002B1C\U00002B50\U00002B55"
    "\U00003030\U0000303D\U00003297\U00003299"
    "\U0001F004\U0001F0CF"
    "\U0001F170-\U0001F171\U0001F17E-\U0001F17F\U0001F18E"
    "\U0001F191-\U0001F19A"
    "\U0001F201-\U0001F202\U0001F21A\U0001F22F"
    "\U0001F232-\U0001F23A\U0001F250-\U0001F251"
    "]"
)
_EMOJI_MOD = "[\U0001F3FB-\U0001F3FF\uFE0E\uFE0F]"
EMOJI_TEXT_OFFSET = 6

_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|(?:" + _EMOJI_BASE_CHARS +
    _EMOJI_MOD + "*"
    "(?:\u200D" + _EMOJI_BASE_CHARS +
    _EMOJI_MOD + "*)*)"
)


def _draw_text_with_fallback(draw: ImageDraw.ImageDraw, xy, text: str, fill, font, canvas=None):
    fc = _get_font_config(int(font.size))
    x, y = xy
    cx = 0.0

    last_end = 0
    for match in _EMOJI_RE.finditer(text):
        if match.start() > last_end:
            seg = text[last_end:match.start()]
            cx += _draw_plain_text(draw, (x + cx, y), seg, fill, fc)
        emoji_text = match.group()
        draw.text((x + cx, y + EMOJI_TEXT_OFFSET), emoji_text, fill=fill, font=fc.emoji, embedded_color=True)
        cx += fc.emoji.getlength(emoji_text)
        last_end = match.end()

    if last_end < len(text):
        seg = text[last_end:]
        cx += _draw_plain_text(draw, (x + cx, y), seg, fill, fc)

    return cx


def _draw_plain_text(draw: ImageDraw.ImageDraw, xy, text: str, fill, fc: FontConfig) -> float:
    x, y = xy
    cx = 0.0
    if not any(_is_tofu(ch, fc.main) for ch in text if ord(ch) > 127):
        draw.text((x, y), text, fill=fill, font=fc.main)
        return fc.main.getlength(text)

    i = 0
    while i < len(text):
        ch = text[i]
        if ord(ch) <= 127 or not _is_tofu(ch, fc.main):
            j = i + 1
            while j < len(text) and (ord(text[j]) <= 127 or not _is_tofu(text[j], fc.main)):
                j += 1
            seg = text[i:j]
            draw.text((x + cx, y), seg, fill=fill, font=fc.main)
            cx += fc.main.getlength(seg)
            i = j
        elif not _is_tofu(ch, fc.fallback):
            j = i + 1
            while j < len(text) and _is_tofu(text[j], fc.main) and not _is_tofu(text[j], fc.fallback):
                j += 1
            seg = text[i:j]
            draw.text((x + cx, y), seg, fill=fill, font=fc.fallback)
            cx += fc.fallback.getlength(seg)
            i = j
        else:
            draw.text((x + cx, y), ch, fill=fill, font=fc.main)
            cx += fc.main.getlength(ch)
            i += 1
    return cx


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_MAIN_FONT_PATH), size)
    except (OSError, IOError):
        return ImageFont.load_default()


FONT_TITLE = _find_font(36, bold=True)
FONT_BODY = _find_font(28)
FONT_SMALL = _find_font(24)
FONT_DURATION = _find_font(28, bold=True)
FONT_STAT_VALUE = _find_font(32, bold=True)
FONT_STAT_LABEL = _find_font(28)


# ── 通用绘图工具 ─────────────────────────────────

def _rounded_rectangle(draw: ImageDraw.ImageDraw, box, radius: int, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _truncate_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    for i in range(len(text), 0, -1):
        if font.getlength(text[:i] + "...") <= max_width:
            return text[:i] + "..."
    return "..."


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 5) -> tuple[list[str], int]:
    lines = []
    current = ""
    consumed = 0
    for ch in text:
        if ch == "\n":
            lines.append(current)
            consumed += len(current) + 1
            current = ""
            if len(lines) >= max_lines:
                break
            continue
        test = current + ch
        if font.getlength(test) > max_width:
            lines.append(current)
            consumed += len(current)
            current = ch
            if len(lines) >= max_lines:
                break
        else:
            current = test
    if current and len(lines) < max_lines:
        lines.append(current)
        consumed += len(current)
    elif current and len(lines) >= max_lines:
        if lines:
            lines[-1] = _truncate_text(lines[-1], font, max_width)
    overflow = len(text) - consumed
    return (lines or [""]), max(overflow, 0)


def _draw_stat_item(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, label: str, value: str):
    val_w = FONT_STAT_VALUE.getlength(value)
    val_x = x + (width - val_w) / 2
    draw.text((val_x, y), value, fill=COLOR_STAT_VALUE, font=FONT_STAT_VALUE)
    lbl_w = FONT_STAT_LABEL.getlength(label)
    lbl_x = x + (width - lbl_w) / 2
    draw.text((lbl_x, y + 42), label, fill=COLOR_STAT_LABEL, font=FONT_STAT_LABEL)


# ── 图片加载 ─────────────────────────────────────

def _load_cover(cover_url: str) -> Image.Image | None:
    try:
        resp = requests.get(cover_url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        w, h = img.size
        target_ratio = CARD_WIDTH / COVER_HEIGHT
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            offset = (w - new_w) // 2
            img = img.crop((offset, 0, offset + new_w, h))
        elif current_ratio < target_ratio:
            new_h = int(w / target_ratio)
            offset = (h - new_h) // 2
            img = img.crop((0, offset, w, offset + new_h))
        img = img.resize((CARD_WIDTH, COVER_HEIGHT), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def _create_placeholder_cover() -> Image.Image:
    img = Image.new("RGB", (CARD_WIDTH, COVER_HEIGHT), (200, 200, 200))
    draw = ImageDraw.Draw(img)
    text = "封面加载失败"
    w = FONT_BODY.getlength(text)
    draw.text(((CARD_WIDTH - w) / 2, COVER_HEIGHT / 2 - 10), text, fill=(150, 150, 150), font=FONT_BODY)
    return img


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


# ── 头像加载 ─────────────────────────────────

def _load_avatar(url: str, size: int = AVATAR_SIZE) -> Image.Image | None:
    """下载头像并裁剪为圆形"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)
        return result
    except Exception:
        return None


def _create_placeholder_avatar(size: int = AVATAR_SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(200, 200, 200, 255))
    return img


# ── 主渲染函数 ────────────────────────────────────
def render_video_card(video: YouTubeVideoInfo, download_cover: bool = True) -> Image.Image:
    """
    将 YouTubeVideoInfo 渲染为卡片图片

    Args:
        video: 视频信息
        download_cover: 是否下载封面图片

    Returns:
        PIL.Image.Image 对象
    """
    content_width = CARD_WIDTH - PADDING * 2

    title_lines, _ = _wrap_text(video.title, FONT_TITLE, content_width, max_lines=5)
    title_line_height = 48
    title_height = len(title_lines) * title_line_height

    total_height = CARD_HEIGHT_BASE + title_height

    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), (0, 0, 0, 0))

    # 背景
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, CARD_WIDTH, total_height), fill=(255, 255, 255))

    # 封面
    if download_cover and video.thumbnail:
        cover = _load_cover(video.thumbnail)
        if cover is None:
            cover = _create_placeholder_cover()
    else:
        cover = _create_placeholder_cover()
    cover_rgba = cover.convert("RGBA")
    canvas.paste(cover_rgba, (0, 0), cover_rgba)

    # 时长标签
    if video.duration > 0:
        dur_text = video.duration_str
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

    # 标题
    y_cursor = COVER_HEIGHT + LINE_GAP
    for line in title_lines:
        _draw_text_with_fallback(draw, (PADDING, y_cursor), line, fill=COLOR_TITLE, font=FONT_TITLE, canvas=canvas)
        y_cursor += title_line_height

    y_cursor += LINE_GAP

    # 频道头像 + 名称
    avatar = None
    if download_cover and video.channel_avatar:
        avatar = _load_avatar(video.channel_avatar, AVATAR_SIZE)
    if not avatar:
        avatar = _create_placeholder_avatar(AVATAR_SIZE)
    canvas.paste(avatar, (PADDING, y_cursor), avatar)

    channel_text = video.channel_title
    text_y = y_cursor + (AVATAR_SIZE - FONT_BODY.size) // 2
    draw.text((PADDING + AVATAR_SIZE + PADDING, text_y), channel_text, fill=COLOR_ACCENT, font=FONT_BODY)

    # YouTube logo
    _draw_logo(canvas, str(_ASSETS_DIR / "youtube.png"), 700, y_cursor + 5, AVATAR_SIZE - 10)

    y_cursor += AVATAR_SIZE + LINE_GAP

    # 发布时间、清晰度、语言
    meta_parts = []
    if video.published_at:
        meta_parts.append(f"发布于 {video.published_at_str}")
    if video.definition:
        meta_parts.append(f"清晰度：{video.definition.upper()}")
    if video.default_audio_language:
        meta_parts.append(f"音轨：{language_name(video.default_audio_language)}")
    meta_text = " | ".join(meta_parts)
    draw.text((PADDING, y_cursor), meta_text, fill=COLOR_DESC_TEXT, font=FONT_SMALL)
    y_cursor += FONT_SMALL.size + LINE_GAP

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
        ("播放", YouTubeVideoInfo.format_count(video.view_count)),
        ("点赞", YouTubeVideoInfo.format_count(video.like_count)),
        ("评论", YouTubeVideoInfo.format_count(video.comment_count)),
        ("字幕轨", str(video.localization_count)),
    ]
    item_width = content_width // len(stats)
    x = PADDING
    for label, value in stats:
        _draw_stat_item(draw, x, y_cursor, item_width, label, value)
        x += item_width
    y_cursor += FONT_STAT_LABEL.size + FONT_STAT_VALUE.size + LINE_GAP * 2

    _draw_copyright(draw, canvas, CARD_WIDTH // 2 - 100, y_cursor)

    return canvas.convert("RGB")


def render_to_bytes(video: YouTubeVideoInfo, fmt: str = "PNG", download_cover: bool = True) -> bytes:
    """渲染并返回图片字节数据"""
    img = render_video_card(video, download_cover=download_cover)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()


# ── 评论区常量 ────────────────────────────────────
COMMENT_CARD_WIDTH = 760
COMMENT_PADDING = 20
COMMENT_AVATAR_SIZE = 48
COMMENT_SUB_AVATAR_SIZE = 36
COLOR_COMMENT_BG = (255, 255, 255)
COLOR_COMMENT_HEADER_TEXT = (0xFF, 0x00, 0x00)
COLOR_COMMENT_HEADER_BG = (0xFF, 0xFF, 0xFF)
COLOR_OWNER_BADGE_BG = (0xFF, 0x00, 0x00)
COLOR_OWNER_BADGE_TEXT = (255, 255, 255)
COLOR_LIKE_TEXT = (0xFF, 0x00, 0x00)
COLOR_TIME_TEXT = (153, 153, 153)
COLOR_REPLY_COUNT = (0xFF, 0x00, 0x00)
COLOR_USERNAME = (51, 51, 51)
COLOR_MESSAGE = (34, 34, 34)
COLOR_SUB_LINE = (229, 233, 239)
COLOR_COMMENT_DIVIDER = (240, 240, 240)
COLOR_OVERFLOW = (120, 120, 120)

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
    """绘制小标签，返回宽度"""
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 3
    _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), 4, bg_color)
    draw.text((x + pad_x, y + pad_y - 2), text, fill=text_color, font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _measure_comment_height(comment: YouTubeCommentItem, content_width: int, is_sub: bool = False) -> int:
    """预计算单条评论所需高度"""
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE

    name_line_h = 28 if is_sub else 30
    text_left = avatar_size + 12
    text_width = content_width - text_left

    msg_line_h = 30 if is_sub else 32
    msg_lines, overflow_count = _wrap_text(comment.text.strip(), font_msg, text_width, max_lines=6)
    msg_h = (len(msg_lines) + (1 if overflow_count > 0 else 0)) * msg_line_h

    meta_h = 28 if is_sub else 30

    h = name_line_h + 6 + msg_h + 8 + meta_h + 12
    return max(h, avatar_size + 16)


def _draw_single_comment(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    comment: YouTubeCommentItem,
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
    avatar = _load_avatar(comment.author_avatar, avatar_size)
    if avatar is None:
        avatar = _create_placeholder_avatar(avatar_size)
    canvas.paste(avatar, (x, y), avatar)

    text_x = x + avatar_size + 12
    text_width = content_width - avatar_size - 12

    # 用户名行: [频道主] 用户名
    name_y = y + 2
    badge_x = text_x

    if comment.is_channel_owner:
        w = _draw_small_badge(draw, badge_x, name_y, "频道主", COLOR_OWNER_BADGE_BG, COLOR_OWNER_BADGE_TEXT)
        badge_x += w + 6

    _draw_text_with_fallback(draw, (badge_x, name_y), comment.author_name, fill=COLOR_USERNAME, font=font_username, canvas=canvas)

    name_line_h = 28 if is_sub else 30
    y += name_line_h + 6

    # 评论内容
    msg_line_h = 30 if is_sub else 32
    msg_lines, overflow_count = _wrap_text(comment.text.strip(), font_msg, text_width, max_lines=5)
    for line in msg_lines:
        _draw_text_with_fallback(draw, (text_x, y), line, fill=COLOR_MESSAGE, font=font_msg, canvas=canvas)
        y += msg_line_h
    if overflow_count > 0:
        overflow_text = f"...（省略 {overflow_count} 字符）"
        draw.text((text_x, y), overflow_text, fill=COLOR_OVERFLOW, font=font_msg)
        y += msg_line_h

    y += 4

    # 底部 meta: 点赞数  时间  回复数
    meta_x = text_x

    if comment.like_count > 0:
        like_text = f"♥ {comment.like_count}"
        draw.text((meta_x, y), like_text, fill=COLOR_LIKE_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(like_text)) + PADDING

    time_text = comment.published_at_str
    if time_text:
        draw.text((meta_x, y), time_text, fill=COLOR_TIME_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(time_text)) + PADDING

    if comment.reply_count > 0 and not is_sub:
        reply_text = f"{comment.reply_count}条回复"
        draw.text((meta_x, y), reply_text, fill=COLOR_REPLY_COUNT, font=font_meta)

    meta_h = 28 if is_sub else 30
    y += meta_h + 12

    return y - start_y


def render_comments_card(comments_data: YouTubeCommentsData, max_comments: int = 15) -> Image.Image:
    """将评论数据渲染为卡片图片"""
    content_width = COMMENT_CARD_WIDTH - COMMENT_PADDING * 2

    # 第一轮：计算总高度
    header_h = 50

    display_comments = comments_data.comments[:max_comments]

    total_h = header_h + COMMENT_PADDING
    max_sub = 2
    for (idx, comment) in enumerate(display_comments):
        total_h += _measure_comment_height(comment, content_width)
        for sub in comment.sub_comments[:max_sub]:
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12
            total_h += _measure_comment_height(sub, sub_width, is_sub=True)
        total_h += 12
        if total_h > 1200:
            display_comments = display_comments[:idx + 1]
            break

    # 创建画布
    canvas = Image.new("RGBA", (COMMENT_CARD_WIDTH, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, total_h), 0, (255, 255, 255, 255))

    # 头部
    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, header_h), 0, COLOR_COMMENT_HEADER_BG)
    header_text = f"评论 ({comments_data.total})"
    header_tw = FONT_COMMENT_HEADER.getlength(header_text)
    height = FONT_COMMENT_HEADER.getbbox(header_text)[3]
    logo_w = _draw_logo(canvas, str(_ASSETS_DIR / "youtube.png"), COMMENT_PADDING * 2, (header_h - 40) // 2, 40)
    _draw_logo(canvas, str(_ASSETS_DIR / "youtube.png"), COMMENT_CARD_WIDTH - COMMENT_PADDING * 2 - logo_w, (header_h - 40) // 2, 40)
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

            for sub in comment.sub_comments[:max_sub]:
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
                fill=COLOR_COMMENT_DIVIDER,
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


def render_comments_to_bytes(comments_data: YouTubeCommentsData, fmt: str = "PNG", max_comments: int = 5) -> bytes:
    """渲染评论卡片并返回图片字节数据"""
    img = render_comments_card(comments_data, max_comments=max_comments)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()
