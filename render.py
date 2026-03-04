"""
视频信息卡片渲染器 - 使用 Pillow 将 VideoInfo 渲染为精美的卡片图片

卡片布局:
┌─────────────────────────────────┐
│          封面图 (16:9)           │
│       右下角: 时长标签            │
├─────────────────────────────────┤
│  标题 (加粗, 最多两行)           │
│  [头像] UP主: xxx    分辨率标签   │
│  发布时间: xxxx-xx-xx            │
├─────────────────────────────────┤
│  截止于 xxxx-xx-xx xx:xx 的数据   │
│  👁 播放  👍 点赞  🪙 投币       │
│  ⭐ 收藏  💬 弹幕  ↗ 转发  💬 评论│
└─────────────────────────────────┘
"""

import io
import re
import random
import platform
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from models import VideoInfo, CommentsData, CommentItem, EmoteInfo, PictureInfo

# ── 常量 ──────────────────────────────────────────
CARD_WIDTH = 800
CARD_HEIGHT = 870
COVER_HEIGHT = 450  # 800 / 16 * 9
PADDING = 16
LINE_GAP = 10
CARD_BG = (255, 255, 255)
CARD_RADIUS = 0
SHADOW_COLOR = (0, 0, 0, 40)
AVATAR_SIZE = 80

COLOR_TITLE = (30, 30, 30)
COLOR_SUB = (102, 102, 102)
COLOR_ACCENT = (251, 114, 153)  # B站粉
COLOR_TAG_BG = (251, 114, 153)
COLOR_TAG_TEXT = (255, 255, 255)
COLOR_STAT_LABEL = (153, 153, 153)
COLOR_STAT_VALUE = (51, 51, 51)
COLOR_DURATION_BG = (0, 0, 0, 180)
COLOR_DURATION_TEXT = (255, 255, 255)
COLOR_DIVIDER = (240, 240, 240)

# ── 字体加载 ─────────────────────────────────────
_ASSETS_DIR = Path(__file__).parent / "assets"
_BUNDLED_FONT = _ASSETS_DIR / "LXGWWenKaiMono-Regular.ttf"

# 回退字体列表：用于主字体缺失的 Unicode 字符 / Emoji
_FALLBACK_FONT_NAMES = [
    "assets/tahoma.ttf",       # Windows - 覆盖大量 Unicode 特殊字符
    "assets/seguisym.ttf",     # Windows - Segoe UI Symbol
    "assets/seguiemj.ttf",     # Windows - Segoe UI Emoji
]
_FALLBACK_FONT_CACHE: dict[int, list[ImageFont.FreeTypeFont]] = {}


def _find_fallback_fonts(size: int) -> list[ImageFont.FreeTypeFont]:
    """加载所有可用的回退字体，结果缓存"""
    if size in _FALLBACK_FONT_CACHE:
        return _FALLBACK_FONT_CACHE[size]
    fonts = []
    for name in _FALLBACK_FONT_NAMES:
        try:
            f = ImageFont.truetype(name, size)
            fonts.append(f)
        except (OSError, IOError):
            continue
    _FALLBACK_FONT_CACHE[size] = fonts
    return fonts


# 主字体 .notdef 参考：用于判断某个字符是否缺失
_NOTDEF_REF: dict[int, bytes] = {}


def _is_tofu(char: str, font: ImageFont.FreeTypeFont) -> bool:
    """判断字符在指定字体中是否为 .notdef (豆腐块)"""
    size_key = int(font.size)
    if size_key not in _NOTDEF_REF:
        _NOTDEF_REF[size_key] = bytes(font.getmask(chr(0xFFFE)))
    return bytes(font.getmask(char)) == _NOTDEF_REF[size_key]


def _find_font_for_char(char: str, main_font: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont | None:
    """为缺失字符寻找能渲染的回退字体"""
    for fb in _find_fallback_fonts(int(main_font.size)):
        if not _is_tofu(char, fb):
            return fb
    return None


# 是否为 Emoji 字符（用于 embedded_color 渲染）
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+"
)


def _draw_text_with_fallback(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fill,
    font: ImageFont.FreeTypeFont,
    canvas: Image.Image | None = None,
) -> float:
    """绘制文本，对主字体缺失的字符自动切换到回退字体。返回占用横向宽度。

    - 普通 Unicode 字符: 用回退字体直接绘制
    - Emoji 字符: 用回退字体 + embedded_color=True 绘制彩色
    """
    # 快速路径：全部字符主字体都能渲染
    has_missing = any(_is_tofu(ch, font) for ch in text if ord(ch) > 127)
    if not has_missing:
        draw.text(xy, text, fill=fill, font=font)
        return font.getlength(text)

    # 逐字符/段分组: 连续可渲染的文字一起绘制，缺失的逐个找回退字体
    x, y = xy
    cx = 0.0
    i = 0
    while i < len(text):
        ch = text[i]
        if ord(ch) <= 127 or not _is_tofu(ch, font):
            # 主字体能渲染 -> 尽量收集连续可渲染字符一起绘制
            j = i + 1
            while j < len(text) and (ord(text[j]) <= 127 or not _is_tofu(text[j], font)):
                j += 1
            segment = text[i:j]
            draw.text((x + cx, y), segment, fill=fill, font=font)
            cx += font.getlength(segment)
            i = j
        else:
            # 主字体缺失 -> 尝试收集连续缺失字符，找同一回退字体
            fb = _find_font_for_char(ch, font)
            if fb:
                j = i + 1
                while j < len(text) and _is_tofu(text[j], font) and not _is_tofu(text[j], fb):
                    j += 1
                segment = text[i:j]
                use_color = bool(_EMOJI_RE.search(segment))
                if use_color and canvas:
                    e_bbox = fb.getbbox(segment)
                    e_w = e_bbox[2] - e_bbox[0]
                    e_h = e_bbox[3] - e_bbox[1]
                    e_img = Image.new("RGBA", (e_w + 4, e_h + 4), (0, 0, 0, 0))
                    e_draw = ImageDraw.Draw(e_img)
                    e_draw.text((-e_bbox[0], -e_bbox[1]), segment, fill=fill, font=fb, embedded_color=True)
                    paste_y = int(y + (font.size - e_h) // 2)
                    canvas.paste(e_img, (int(x + cx), paste_y), e_img)
                    cx += e_w + 2
                else:
                    kwargs = {"embedded_color": True} if use_color else {}
                    draw.text((x + cx, y), segment, fill=fill, font=fb, **kwargs)
                    cx += fb.getlength(segment)
                i = j
            else:
                # 全部回退字体都没有 -> 用主字体画豆腐块
                draw.text((x + cx, y), ch, fill=fill, font=font)
                cx += font.getlength(ch)
                i += 1
    return cx


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """加载字体，优先使用 assets 目录下的 LXGW 文楷等宽"""
    if _BUNDLED_FONT.exists():
        try:
            return ImageFont.truetype(str(_BUNDLED_FONT), size)
        except Exception:
            pass

FONT_TITLE = _find_font(36, bold=True)
FONT_BODY = _find_font(28)
FONT_SMALL = _find_font(24)
FONT_TAG = _find_font(24, bold=True)
FONT_DURATION = _find_font(28, bold=True)
FONT_STAT_VALUE = _find_font(32, bold=True)
FONT_STAT_LABEL = _find_font(28)


# ── 绘图工具函数 ────────────────────────────────────
def _rounded_rectangle(draw: ImageDraw.ImageDraw, xy, radius, fill):
    """绘制圆角矩形"""
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_tag(draw: ImageDraw.ImageDraw, xy, text: str, font, bg_color, text_color, radius=6):
    """绘制带圆角背景的标签"""
    x, y = xy
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 20, 10
    _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), radius, bg_color)
    draw.text((x + pad_x, y + pad_y -3), text, fill=text_color, font=font)
    return tw + pad_x * 2


def _truncate_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """截断文字并添加省略号"""
    if font.getlength(text) <= max_width:
        return text
    for i in range(len(text), 0, -1):
        truncated = text[:i] + "..."
        if font.getlength(truncated) <= max_width:
            return truncated
    return "..."


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 3) -> list[str]:
    """文字换行, 最多 max_lines 行"""
    lines = []
    current = ""
    for ch in text:
        if ch == '\n':
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                lines[-1] = _truncate_text(lines[-1], font, max_width)
                return lines
            continue
        test = current + ch
        if font.getlength(test) > max_width:
            lines.append(current)
            current = ch
            if len(lines) >= max_lines:
                # 最后一行截断
                lines[-1] = _truncate_text(lines[-1], font, max_width)
                return lines
        else:
            current = test
    if current:
        if len(lines) >= max_lines:
            lines[-1] = _truncate_text(lines[-1], font, max_width)
        else:
            lines.append(current)
    return lines


def _draw_stat_item(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str) -> int:
    """绘制单个统计项: 数值 + 标签, 返回占用宽度"""
    # 数值
    draw.text((x, y), value, fill=COLOR_STAT_VALUE, font=FONT_STAT_VALUE)
    val_w = FONT_STAT_VALUE.getlength(value)
    # 标签
    label_bbox = FONT_STAT_LABEL.getbbox(label)
    label_h = label_bbox[3] - label_bbox[1]
    draw.text((x, y + 42), label, fill=COLOR_STAT_LABEL, font=FONT_STAT_LABEL)
    label_w = FONT_STAT_LABEL.getlength(label)
    return int(max(val_w, label_w)) + 40


# ── 头像处理 ─────────────────────────────────────
def _load_avatar(avatar_url: str, size: int = AVATAR_SIZE) -> Image.Image | None:
    """下载头像并裁剪为圆形"""
    try:
        import urllib.request
        req = urllib.request.Request(avatar_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        # 圆形遮罩
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size, size), fill=255)
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)
        return result
    except Exception as e:
        print(f"头像加载失败: {e}")
        return None


def _create_placeholder_avatar(size: int = AVATAR_SIZE) -> Image.Image:
    """创建默认圆形头像占位图"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(200, 200, 200, 255))
    # 简单的人形图标
    cx, cy = size // 2, size // 2
    r = size // 6
    draw.ellipse((cx - r, cy - r - 4, cx + r, cy + r - 4), fill=(160, 160, 160, 255))
    draw.ellipse((cx - r - 2, cy + r - 2, cx + r + 2, cy + r + 6), fill=(160, 160, 160, 255))
    return img


# ── 表情包加载与缓存 ─────────────────────────────────
_emote_cache: dict[str, Image.Image | None] = {}


def _load_emote(url: str, size: int) -> Image.Image | None:
    """下载并缓存表情包图片，返回指定尺寸的 RGBA 图片"""
    cache_key = f"{url}_{size}"
    if cache_key in _emote_cache:
        cached = _emote_cache[cache_key]
        return cached.copy() if cached else None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        _emote_cache[cache_key] = img
        return img.copy()
    except Exception as e:
        print(f"表情加载失败: {e}")
        _emote_cache[cache_key] = None
        return None


def _parse_message_segments(message: str, emotes: dict[str, EmoteInfo]) -> list[tuple[str, str | EmoteInfo]]:
    """将评论消息解析为文本和表情段落列表

    Returns:
        list of ('text', str) or ('emote', EmoteInfo)
    """
    if not emotes:
        return [('text', message)]

    # 按长度降序排列，避免匹配到短前缀
    sorted_keys = sorted(emotes.keys(), key=len, reverse=True)
    pattern = '|'.join(re.escape(key) for key in sorted_keys)

    segments: list[tuple[str, str | EmoteInfo]] = []
    last_end = 0
    for match in re.finditer(pattern, message):
        if match.start() > last_end:
            segments.append(('text', message[last_end:match.start()]))
        emote_key = match.group()
        segments.append(('emote', emotes[emote_key]))
        last_end = match.end()
    if last_end < len(message):
        segments.append(('text', message[last_end:]))

    return segments if segments else [('text', message)]


def _wrap_message_segments(
    segments: list[tuple[str, str | EmoteInfo]],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int = 6,
    emote_size: int = 30,
) -> list[list[tuple[str, str | EmoteInfo]]]:
    """将混合文本+表情段落列表按宽度换行

    Returns:
        list of lines, each line is a list of ('text', str) or ('emote', EmoteInfo)
    """
    lines: list[list[tuple[str, str | EmoteInfo]]] = []
    current_line: list[tuple[str, str | EmoteInfo]] = []
    current_width = 0.0

    for seg_type, seg_data in segments:
        if seg_type == 'emote':
            emote_w = emote_size + 2
            if current_width + emote_w > max_width and current_line:
                lines.append(current_line)
                if len(lines) >= max_lines:
                    return lines
                current_line = []
                current_width = 0.0
            current_line.append(('emote', seg_data))
            current_width += emote_w
        else:  # text
            for ch in seg_data:
                if ch == '\n':
                    lines.append(current_line)
                    current_line = []
                    current_width = 0.0
                    if len(lines) >= max_lines:
                        return lines
                    continue
                ch_width = font.getlength(ch)
                if current_width + ch_width > max_width and current_line:
                    lines.append(current_line)
                    if len(lines) >= max_lines:
                        return lines
                    current_line = []
                    current_width = 0.0
                # 追加字符到当前行最后一个文本段，或新建文本段
                if current_line and current_line[-1][0] == 'text':
                    current_line[-1] = ('text', current_line[-1][1] + ch)
                else:
                    current_line.append(('text', ch))
                current_width += ch_width

    if current_line:
        if len(lines) < max_lines:
            lines.append(current_line)

    return lines if lines else [[('text', '')]]


def _draw_message_with_emotes(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    wrapped_lines: list[list[tuple[str, str | EmoteInfo]]],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    line_height: int,
    emote_size: int,
    text_color: tuple | None = None,
) -> int:
    """绘制包含表情包的消息文本，返回占用的总高度"""
    if text_color is None:
        text_color = (34, 34, 34)  # COLOR_MESSAGE
    total_h = 0
    for line_segments in wrapped_lines:
        cx = x
        for seg_type, seg_data in line_segments:
            if seg_type == 'text':
                tw = _draw_text_with_fallback(draw, (cx, y), seg_data, fill=text_color, font=font, canvas=canvas)
                cx += int(tw)
            elif seg_type == 'emote':
                emote_img = _load_emote(seg_data.url, emote_size)
                if emote_img:
                    # 表情垂直居中对齐文本
                    emote_y = y + (line_height - emote_size) // 2
                    canvas.paste(emote_img, (int(cx), int(emote_y)), emote_img)
                    cx += emote_size + 2
                else:
                    # 加载失败时回退显示表情文字
                    draw.text((cx, y), seg_data.text, fill=text_color, font=font)
                    cx += int(font.getlength(seg_data.text))
        y += line_height
        total_h += line_height
    return total_h


# ── 评论配图处理 ─────────────────────────────────
COMMENT_PIC_MAX_WIDTH = 700  # 配图最大显示宽度
COMMENT_PIC_MAX_HEIGHT = 200  # 配图最大显示高度
COMMENT_PIC_GAP = 8  # 多张图之间的间距
COMMENT_PIC_RADIUS = 8  # 配图圆角

_picture_cache: dict[str, Image.Image | None] = {}


def _load_comment_picture(url: str, max_w: int = COMMENT_PIC_MAX_WIDTH, max_h: int = COMMENT_PIC_MAX_HEIGHT) -> Image.Image | None:
    """下载评论配图并缩放到适当尺寸，结果带圆角"""
    cache_key = f"{url}_{max_w}_{max_h}"
    if cache_key in _picture_cache:
        cached = _picture_cache[cache_key]
        return cached.copy() if cached else None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")

        # 等比缩放使宽和高都不超过限制
        w, h = img.size
        scale = min(max_w / w, max_h / h, 1.0)
        new_w = int(w * scale)
        new_h = int(h * scale)
        if scale < 1.0:
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 圆角遮罩
        mask = Image.new("L", (new_w, new_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle((0, 0, new_w, new_h), COMMENT_PIC_RADIUS, fill=255)
        result = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)

        _picture_cache[cache_key] = result
        return result.copy()
    except Exception as e:
        print(f"评论配图加载失败: {e}")
        _picture_cache[cache_key] = None
        return None


def _measure_pictures_height(pictures: list[PictureInfo], max_w: int) -> int:
    """预计算配图区域高度（横向排布，宽度不够时换行）"""
    if not pictures:
        return 0
    total_h = 8  # 上方间距
    cx = 0
    row_h = 0
    for pic in pictures:
        if pic.img_width > 0 and pic.img_height > 0:
            scale = min(COMMENT_PIC_MAX_WIDTH / pic.img_width, COMMENT_PIC_MAX_HEIGHT / pic.img_height, 1.0)
            pic_w = int(pic.img_width * scale)
            pic_h = int(pic.img_height * scale)
        else:
            pic_w, pic_h = COMMENT_PIC_MAX_WIDTH, COMMENT_PIC_MAX_HEIGHT
        # 检查当前行是否放得下
        if cx > 0 and cx + COMMENT_PIC_GAP + pic_w > max_w:
            # 换行
            total_h += row_h + COMMENT_PIC_GAP
            cx = 0
            row_h = 0
        cx += pic_w + COMMENT_PIC_GAP
        row_h = max(row_h, pic_h)
    total_h += row_h + COMMENT_PIC_GAP
    return total_h


def _draw_pictures(
    canvas: Image.Image,
    pictures: list[PictureInfo],
    x: int,
    y: int,
    max_w: int,
) -> int:
    """绘制评论配图（横向排布），返回占用总高度"""
    if not pictures:
        return 0
    start_y = y
    y += 8  # 上方间距
    cx = x
    row_h = 0
    for pic in pictures:
        pic_img = _load_comment_picture(pic.img_src)
        if pic_img:
            pw, ph = pic_img.size
        else:
            # 占位尺寸
            if pic.img_width > 0 and pic.img_height > 0:
                scale = min(COMMENT_PIC_MAX_WIDTH / pic.img_width, COMMENT_PIC_MAX_HEIGHT / pic.img_height, 1.0)
                pw = int(pic.img_width * scale)
                ph = int(pic.img_height * scale)
            else:
                pw, ph = COMMENT_PIC_MAX_WIDTH, 80

        # 检查当前行是否放得下
        if cx > x and cx + COMMENT_PIC_GAP + pw > x + max_w:
            # 换行
            y += row_h + COMMENT_PIC_GAP
            cx = x
            row_h = 0

        if pic_img:
            canvas.paste(pic_img, (cx, y), pic_img)
        else:
            # 加载失败时绘制占位框
            placeholder = Image.new("RGBA", (pw, ph), (240, 240, 240, 255))
            ph_draw = ImageDraw.Draw(placeholder)
            ph_draw.rounded_rectangle((0, 0, pw, ph), COMMENT_PIC_RADIUS, outline=(200, 200, 200), width=1)
            ph_text = "图片加载失败"
            ph_font = FONT_COMMENT_META
            tw = ph_font.getlength(ph_text)
            ph_draw.text(((pw - tw) / 2, ph / 2 - 10), ph_text, fill=(180, 180, 180), font=ph_font)
            canvas.paste(placeholder, (cx, y), placeholder)

        cx += pw + COMMENT_PIC_GAP
        row_h = max(row_h, ph)

    y += row_h + COMMENT_PIC_GAP
    return y - start_y


# ── 封面处理 ─────────────────────────────────────
def _load_cover(cover_url: str) -> Image.Image | None:
    """下载并加载封面图片"""
    try:
        import urllib.request
        req = urllib.request.Request(cover_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        # 裁剪为 16:9
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
    except Exception as e:
        print(f"封面加载失败: {e}")
        return None


def _create_placeholder_cover() -> Image.Image:
    """创建默认封面占位图"""
    img = Image.new("RGB", (CARD_WIDTH, COVER_HEIGHT), (200, 200, 200))
    draw = ImageDraw.Draw(img)
    text = "封面加载失败"
    w = FONT_BODY.getlength(text)
    draw.text(((CARD_WIDTH - w) / 2, COVER_HEIGHT / 2 - 10), text, fill=(150, 150, 150), font=FONT_BODY)
    return img


# ── 弹幕绘制 ─────────────────────────────────────
FONT_DANMAKU = _find_font(28, bold=True)
COLOR_DANMAKU_SHADOW = (0, 0, 0)  # 描边/阴影色

def _draw_danmaku_on_cover(cover: Image.Image, danmaku_list: list[str]) -> Image.Image:
    """
    将弹幕列表绘制到封面图上，模拟 B 站弹幕滚动效果。
    弹幕按行分布，在水平方向上随机偏移，白色文字带黑色描边。
    """
    if not danmaku_list:
        return cover

    overlay = cover.copy().convert("RGBA")
    txt_layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    cover_w, cover_h = overlay.size
    font = FONT_DANMAKU
    line_height = 40  # 行高
    margin_top = 20
    margin_bottom = 60  # 底部留出空间给时长标签

    # 可用行数
    available_h = cover_h - margin_top - margin_bottom
    max_rows = max(1, available_h // line_height)

    # 为每条弹幕分配行位置和随机水平偏移
    rng = random.Random()  # 固定种子使结果可复现
    for i, text in enumerate(danmaku_list):
        row = i % max_rows
        y = margin_top + row * line_height

        text_w = font.getlength(text)
        # 水平位置：在可用范围内随机偏移，错开同行弹幕
        max_x = max(0, cover_w - text_w - 20)
        x = rng.randint(10, max(10, int(max_x)))

        # 描边效果：四个方向各偏移 1px 画黑色文字
        stroke_offsets = [(-1, -1), (-1, 1), (1, -1), (1, 1), (-2, 0), (2, 0), (0, -2), (0, 2)]
        for dx, dy in stroke_offsets:
            draw.text((x + dx, y + dy), text, fill=(0, 0, 0, 200), font=font)

        # 白色弹幕文字，带半透明度
        draw.text((x, y), text, fill=(255, 255, 255, 230), font=font)

    overlay = Image.alpha_composite(overlay, txt_layer)
    return overlay.convert("RGB")


# ── 主渲染函数 ────────────────────────────────────
def render_video_card(video: VideoInfo, download_cover: bool = True, danmaku_list: list[str] | None = None) -> Image.Image:
    """
    将 VideoInfo 渲染为卡片图片

    Args:
        video: 视频信息
        download_cover: 是否下载封面图片（False 时使用占位图）
        danmaku_list: 弹幕文字列表，绘制到封面上

    Returns:
        PIL.Image.Image 对象
    """
    content_width = CARD_WIDTH - PADDING * 2

    # ── 预计算文字行数确定卡片高度 ──
    title_lines = _wrap_text(video.title, FONT_TITLE, content_width)
    title_line_height = 52
    title_height = len(title_lines) * title_line_height

    total_height = CARD_HEIGHT - (2-len(title_lines))*title_line_height

    # ── 创建画布 ──
    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), (0, 0, 0, 0))
    # 卡片背景
    card_draw = ImageDraw.Draw(canvas)
    _rounded_rectangle(card_draw, (0, 0, CARD_WIDTH, total_height), CARD_RADIUS, (255, 255, 255, 255))

    # 在卡片上绘制内容
    draw = ImageDraw.Draw(canvas)

    # ── 封面 ──
    if download_cover and video.cover:
        cover = _load_cover(video.cover)
    else:
        cover = None

    if cover is None:
        cover = _create_placeholder_cover()

    # 在封面上绘制弹幕
    if danmaku_list:
        cover = _draw_danmaku_on_cover(cover, danmaku_list)

    # 封面圆角遮罩（上方两个角）
    cover_mask = Image.new("L", (CARD_WIDTH, COVER_HEIGHT), 0)
    mask_draw = ImageDraw.Draw(cover_mask)
    mask_draw.rounded_rectangle((0, 0, CARD_WIDTH, COVER_HEIGHT + CARD_RADIUS), CARD_RADIUS, fill=255)
    cover_rgba = cover.convert("RGBA")
    # 用遮罩粘贴
    canvas.paste(cover_rgba, (0, 0), cover_mask)

    # ── 封面上的时长标签 ──
    dur_text = video.duration_str
    dur_bbox = FONT_DURATION.getbbox(dur_text)
    dur_tw = dur_bbox[2] - dur_bbox[0]
    dur_th = dur_bbox[3] - dur_bbox[1]
    dur_pad_x, dur_pad_y = 12, 6
    dur_x = CARD_WIDTH - dur_tw - dur_pad_x * 2 - 16
    dur_y = COVER_HEIGHT - dur_th - dur_pad_y * 2 - 16
    # 半透明背景
    dur_overlay = Image.new("RGBA", (dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), (0, 0, 0, 0))
    dur_draw = ImageDraw.Draw(dur_overlay)
    _rounded_rectangle(dur_draw, (0, 0, dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), 4, (0, 0, 0, 180))
    canvas.paste(dur_overlay, (dur_x, dur_y), dur_overlay)
    draw.text((dur_x + dur_pad_x, dur_y + dur_pad_y - 5), dur_text, fill=COLOR_DURATION_TEXT, font=FONT_DURATION)

    # ── 标题 ──
    y_cursor = COVER_HEIGHT + PADDING
    for line in title_lines:
        draw.text((PADDING, y_cursor), line, fill=COLOR_TITLE, font=FONT_TITLE)
        y_cursor += title_line_height

    y_cursor += LINE_GAP

    # ── UP主头像 + 名字 + 分辨率标签 ──
    avatar_sz = AVATAR_SIZE
    if download_cover and video.author_face:
        avatar = _load_avatar(video.author_face, avatar_sz)
    else:
        avatar = None
    if avatar is None:
        avatar = _create_placeholder_avatar(avatar_sz)

    # 粘贴圆形头像
    canvas.paste(avatar, (PADDING, y_cursor), avatar)

    # 文字垂直居中到头像
    author_text = video.author_name
    text_y = y_cursor + (avatar_sz - 30) // 2
    draw.text((PADDING + avatar_sz + 12, text_y), author_text, fill=COLOR_SUB, font=FONT_BODY)

    # 分辨率标签
    res_text = video.resolution_str
    tag_x = CARD_WIDTH - PADDING - FONT_TAG.getlength(res_text) - 24
    _draw_tag(draw, (tag_x, y_cursor + (avatar_sz - 34) // 2), res_text, FONT_TAG, COLOR_TAG_BG, COLOR_TAG_TEXT)

    y_cursor += avatar_sz + LINE_GAP

    # ── 发布时间 + BV号 ──
    time_text = f"发布于 {video.publish_time_str}    {video.bvid}"
    draw.text((PADDING, y_cursor), time_text, fill=COLOR_STAT_LABEL, font=FONT_SMALL)

    y_cursor += 28 + PADDING

    # ── 分割线 ──
    draw.line((PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor), fill=COLOR_DIVIDER, width=2)
    y_cursor += PADDING // 2 + 4

    # ── 数据快照时间说明 ──
    from datetime import datetime
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot_text = f"截止于 {snapshot_time} 的数据"
    snapshot_w = FONT_SMALL.getlength(snapshot_text)
    draw.text(((CARD_WIDTH - snapshot_w) / 2, y_cursor), snapshot_text, fill=COLOR_STAT_LABEL, font=FONT_SMALL)
    y_cursor += 30 + LINE_GAP

    # ── 统计数据 ──
    stats = [
        ("播放", VideoInfo.format_count(video.view)),
        ("点赞", VideoInfo.format_count(video.like)),
        ("投币", VideoInfo.format_count(video.coin)),
        ("收藏", VideoInfo.format_count(video.favorite)),
        ("弹幕", VideoInfo.format_count(video.danmaku)),
        ("评论", VideoInfo.format_count(video.reply)),
        ("转发", VideoInfo.format_count(video.share)),
    ]

    # 均匀分布
    item_width = content_width // len(stats)
    x = PADDING
    for label, value in stats:
        _draw_stat_item(draw, x, y_cursor, label, value)
        x += item_width + 10

    return canvas.convert("RGB")


def render_to_bytes(video: VideoInfo, fmt: str = "PNG", download_cover: bool = True, danmaku_list: list[str] | None = None) -> bytes:
    """渲染并返回图片字节数据"""
    img = render_video_card(video, download_cover=download_cover, danmaku_list=danmaku_list)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()


# ── 评论区颜色常量 ────────────────────────────────
COMMENT_CARD_WIDTH = 800
COMMENT_PADDING = 20
COMMENT_AVATAR_SIZE = 48
COMMENT_SUB_AVATAR_SIZE = 36
COLOR_COMMENT_BG = (255, 255, 255)
COLOR_COMMENT_HEADER_BG = (251, 114, 153)
COLOR_COMMENT_HEADER_TEXT = (255, 255, 255)
COLOR_UP_BADGE_BG = (251, 114, 153)
COLOR_UP_BADGE_TEXT = (255, 255, 255)
COLOR_TOP_BADGE_BG = (255, 215, 0)
COLOR_TOP_BADGE_TEXT = (100, 70, 0)
COLOR_VIP_BADGE_BG = (251, 114, 153)
COLOR_VIP_BADGE_TEXT = (255, 255, 255)
COLOR_CONTRACTOR_BG = (230, 230, 230)
COLOR_CONTRACTOR_TEXT = (120, 120, 120)
COLOR_LEVEL_COLORS = {
    0: (191, 191, 191),
    1: (191, 191, 191),
    2: (149, 221, 178),
    3: (109, 192, 233),
    4: (255, 179, 76),
    5: (255, 108, 0),
    6: (255, 0, 0),
}
COLOR_LIKE_ICON = (153, 153, 153)
COLOR_LIKE_TEXT = (0xaa, 0x37, 0x31)
COLOR_TIME_TEXT = (153, 153, 153)
COLOR_REPLY_COUNT = (109, 192, 233)
COLOR_USERNAME = (51, 51, 51)
COLOR_MESSAGE = (34, 34, 34)
COLOR_SUB_LINE = (229, 233, 239)

# 评论区字体
FONT_COMMENT_HEADER = _find_font(24, bold=True)
FONT_COMMENT_USERNAME = _find_font(24, bold=True)
FONT_COMMENT_MESSAGE = _find_font(24)
FONT_COMMENT_META = _find_font(20)
FONT_COMMENT_BADGE = _find_font(18, bold=True)
FONT_COMMENT_SUB_USERNAME = _find_font(22, bold=True)
FONT_COMMENT_SUB_MESSAGE = _find_font(22)
FONT_COMMENT_SUB_META = _find_font(18)


def _draw_level_badge(draw: ImageDraw.ImageDraw, x: int, y: int, level: int) -> int:
    """绘制用户等级徽章，返回占用宽度"""
    color = COLOR_LEVEL_COLORS.get(level, (191, 191, 191))
    text = f"Lv{level}"
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 4
    _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), 4, color)
    draw.text((x + pad_x, y + pad_y - 5), text, fill=(255, 255, 255), font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _draw_small_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, bg_color, text_color) -> int:
    """绘制小型徽章，返回占用宽度"""
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 3
    _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), 4, bg_color)
    draw.text((x + pad_x, y + pad_y - 2), text, fill=text_color, font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _measure_comment_height(comment: CommentItem, content_width: int, is_sub: bool = False) -> int:
    """预计算单条评论所需高度"""
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE

    # 用户名行高度
    name_line_h = 30 if is_sub else 34

    # 消息文本区域宽度
    text_left = avatar_size + 12
    text_width = content_width - text_left

    # 消息行数（考虑表情包宽度）
    msg_line_h = 32 if is_sub else 34
    emote_size = msg_line_h - 2
    segments = _parse_message_segments(comment.message, comment.emotes)
    wrapped = _wrap_message_segments(segments, font_msg, text_width, max_lines=6, emote_size=emote_size)
    msg_h = len(wrapped) * msg_line_h

    # 底部 meta 行（点赞、时间等）
    meta_h = 28 if is_sub else 30

    # 配图高度
    pic_h = 0
    if comment.pictures and not is_sub:
        pic_max_w = min(text_width, COMMENT_PIC_MAX_WIDTH)
        pic_h = _measure_pictures_height(comment.pictures, pic_max_w)

    # 总高度 = 用户名行 + 消息 + 配图 + meta行 + 间距
    h = name_line_h + 6 + msg_h + pic_h + 8 + meta_h + 12

    return max(h, avatar_size + 16)


def _draw_single_comment(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    comment: CommentItem,
    x: int,
    y: int,
    content_width: int,
    is_sub: bool = False,
) -> int:
    """
    绘制单条评论，返回占用的高度。

    Args:
        canvas: 画布（用于粘贴头像）
        draw: ImageDraw 对象
        comment: 评论数据
        x: 起始 X 坐标
        y: 起始 Y 坐标
        content_width: 可用内容宽度
        is_sub: 是否为子评论
    """
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE
    font_username = FONT_COMMENT_SUB_USERNAME if is_sub else FONT_COMMENT_USERNAME
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    font_meta = FONT_COMMENT_SUB_META if is_sub else FONT_COMMENT_META

    start_y = y

    # ── 头像 ──
    avatar = _load_avatar(comment.avatar, avatar_size)
    if avatar is None:
        avatar = _create_placeholder_avatar(avatar_size)
    canvas.paste(avatar, (x, y), avatar)

    text_x = x + avatar_size + 12
    text_width = content_width - avatar_size - 12

    # ── 用户名行: [置顶] [UP] 用户名 [Lv] [VIP] [粉丝] ──
    name_y = y + 2
    badge_x = text_x

    # 置顶标签
    if comment.is_top:
        w = _draw_small_badge(draw, badge_x, name_y, "置顶", COLOR_TOP_BADGE_BG, COLOR_TOP_BADGE_TEXT)
        badge_x += w + 6

    # UP主标签
    if comment.is_up:
        w = _draw_small_badge(draw, badge_x, name_y+3, "UP", COLOR_UP_BADGE_BG, COLOR_UP_BADGE_TEXT)
        badge_x += w + 6

    # 用户名
    uname_display = _truncate_text(comment.uname, font_username, text_width - (badge_x - text_x) - 120)
    uname_color = (251, 114, 153) if comment.is_vip else COLOR_USERNAME
    draw.text((badge_x, name_y), uname_display, fill=uname_color, font=font_username)
    badge_x += int(font_username.getlength(uname_display)) + 8

    # 等级徽章
    level_y = name_y + 3
    w = _draw_level_badge(draw, badge_x, level_y+2, comment.level)
    badge_x += w + 6

    # VIP标签
    if comment.is_vip and comment.vip_label:
        w = _draw_small_badge(draw, badge_x, level_y, comment.vip_label, COLOR_VIP_BADGE_BG, COLOR_VIP_BADGE_TEXT)
        badge_x += w + 6

    # 原始粉丝标签
    if comment.is_contractor and comment.contract_desc:
        w = _draw_small_badge(draw, badge_x, level_y, comment.contract_desc, COLOR_CONTRACTOR_BG, COLOR_CONTRACTOR_TEXT)
        badge_x += w + 6

    name_line_h = 30 if is_sub else 34
    y += name_line_h + 6

    # ── 评论内容（支持表情包） ──
    msg_line_h = 32 if is_sub else 34
    emote_size = msg_line_h - 2
    segments = _parse_message_segments(comment.message, comment.emotes)
    wrapped = _wrap_message_segments(segments, font_msg, text_width, max_lines=6, emote_size=emote_size)
    msg_h = _draw_message_with_emotes(canvas, draw, wrapped, text_x, y, font_msg, msg_line_h, emote_size)
    y += msg_h

    # ── 评论配图 ──
    if comment.pictures and not is_sub:
        pic_max_w = min(text_width, COMMENT_PIC_MAX_WIDTH)
        pic_h = _draw_pictures(canvas, comment.pictures, text_x, y, pic_max_w)
        y += pic_h

    y += 8

    # ── 底部 meta: 👍 点赞数  时间  回复数 ──
    meta_x = text_x

    # 点赞
    like_text = f"{comment.like}赞"
    draw.text((meta_x, y), like_text, fill=COLOR_LIKE_TEXT, font=font_meta)
    meta_x += int(font_meta.getlength(like_text)) + 20

    # 时间
    time_text = comment.time_desc if comment.time_desc else ""
    if time_text:
        draw.text((meta_x, y), time_text, fill=COLOR_TIME_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(time_text)) + 20

    # 回复数
    if comment.rcount > 0 and not is_sub:
        reply_text = f"{comment.rcount}条回复"
        draw.text((meta_x, y), reply_text, fill=COLOR_REPLY_COUNT, font=font_meta)

    meta_h = 28 if is_sub else 30
    y += meta_h + 12

    return y - start_y


def render_comments_card(comments_data: CommentsData, max_comments: int = 15) -> Image.Image:
    """
    将评论数据渲染为卡片图片

    Args:
        comments_data: 评论数据
        max_comments: 最多显示的评论数量

    Returns:
        PIL.Image.Image 对象
    """
    content_width = COMMENT_CARD_WIDTH - COMMENT_PADDING * 2

    # ── 第一轮：计算总高度 ──
    header_h = 40  # 顶部 "评论 (N)" 区域

    # 收集要显示的评论
    display_comments: list[tuple[CommentItem, bool]] = []  # (comment, is_top)

    if comments_data.top_comment:
        display_comments.append((comments_data.top_comment, True))

    for c in comments_data.comments[:max_comments]:
        display_comments.append((c, False))

    # 预计算高度
    total_h = header_h + COMMENT_PADDING
    for comment, _ in display_comments:
        total_h += _measure_comment_height(comment, content_width)
        # 子评论
        for sub in comment.sub_replies:
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12
            total_h += _measure_comment_height(sub, sub_width, is_sub=True)
        # 分隔线
        total_h += 12

    # ── 创建画布 ──
    canvas = Image.new("RGBA", (COMMENT_CARD_WIDTH, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # 背景
    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, total_h), 0, (255, 255, 255, 255))

    # ── 头部：评论 (N) ──
    _rounded_rectangle(
        draw,
        (0, 0, COMMENT_CARD_WIDTH, header_h),
        0,
        COLOR_COMMENT_HEADER_BG,
    )
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

    # ── 逐条绘制评论 ──
    for idx, (comment, is_top) in enumerate(display_comments):
        h = _draw_single_comment(canvas, draw, comment, COMMENT_PADDING, y_cursor, content_width)
        y_cursor += h

        # 子评论
        if comment.sub_replies:
            sub_x = COMMENT_PADDING + COMMENT_AVATAR_SIZE + 12
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12

            # 子评论区域左侧竖线
            line_x = sub_x - 6
            sub_start_y = y_cursor

            for sub in comment.sub_replies:
                sub_h = _draw_single_comment(canvas, draw, sub, sub_x, y_cursor, sub_width, is_sub=True)
                y_cursor += sub_h

            # 画左侧连接线
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

    # 裁切到实际高度
    actual_h = y_cursor + COMMENT_PADDING
    if actual_h < total_h:
        canvas = canvas.crop((0, 0, COMMENT_CARD_WIDTH, actual_h))

    return canvas.convert("RGB")


def render_comments_to_bytes(comments_data: CommentsData, fmt: str = "PNG", max_comments: int = 15) -> bytes:
    """渲染评论卡片并返回图片字节数据"""
    img = render_comments_card(comments_data, max_comments=max_comments)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()
