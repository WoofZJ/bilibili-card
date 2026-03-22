import io
import re
import random
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from models import VideoInfo, CommentsData, CommentItem, EmoteInfo, PictureInfo, JumpUrlInfo

# ── 常量 ──────────────────────────────────────────
CARD_WIDTH = 800
CARD_HEIGHT_BASE = 738
COVER_HEIGHT = 450  # 800 / 16 * 9
PADDING = 16
LINE_GAP = 10
CARD_BG = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0, 40)
AVATAR_SIZE = 60
EMOJI_TEXT_OFFSET = 6

COLOR_TITLE = (30, 30, 30)
COLOR_SUB = (102, 102, 102)
COLOR_ACCENT = (251, 114, 153)  # B站粉
COLOR_DESC_TEXT = (153, 153, 153)
COLOR_STAT_LABEL = (153, 153, 153)
COLOR_STAT_VALUE = (51, 51, 51)
COLOR_DURATION_BG = (0, 0, 0, 180)
COLOR_DURATION_TEXT = (255, 255, 255)
COLOR_DIVIDER = (240, 240, 240)
COLOR_OVERFLOW = (120, 120, 120)
COLOR_LINK = (0x00, 0x6B, 0xDE) # 链接颜色

# ── 字体加载 ─────────────────────────────────────
_ASSETS_DIR = Path(__file__).parent / "assets"

# ── 字体路径 ──────────────────────────────────────
_MAIN_FONT_PATH = _ASSETS_DIR / "LXGWWenKaiMono-Regular.ttf"
_EMOJI_FONT_PATH = _ASSETS_DIR / "seguiemj.ttf"
_FALLBACK_FONT_PATH = _ASSETS_DIR / "tahoma.ttf"


class FontConfig:
    """字体配置：主字体、emoji 字体、回退字体"""
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
    """获取指定尺寸的字体配置（带缓存）"""
    if size not in _font_config_cache:
        _font_config_cache[size] = FontConfig(size)
    return _font_config_cache[size]


# 主字体 .notdef 参考：用于判断某个字符是否缺失
_NOTDEF_REF: dict[tuple, bytes] = {}


def _is_tofu(char: str, font: ImageFont.FreeTypeFont) -> bool:
    """判断字符在指定字体中是否为 .notdef (豆腐块)"""
    key = (int(font.size), *font.getname())
    if key not in _NOTDEF_REF:
        _NOTDEF_REF[key] = bytes(font.getmask(chr(0xFFFE)))
    return bytes(font.getmask(char)) == _NOTDEF_REF[key]


# ── Emoji 正则：匹配完整的 emoji 序列（含肤色修饰符、ZWJ 等）──
_EMOJI_BASE_CHARS = (
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport & Map
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols
    "\U0001FA00-\U0001FAFF"  # Extended-A
    "\U00002600-\U000027BF"  # Misc Symbols & Dingbats
    "\U0000203C\U00002049"   # ‼⁉
    "\U00002139\U00002328"   # ℹ⌨
    "\U0000231A\U0000231B"   # ⌚⌛
    "\U000023CF"             # ⏏
    "\U000023E9-\U000023F3"  # ⏩-⏳
    "\U000023F8-\U000023FA"  # ⏸-⏺
    "\U000024C2"             # Ⓜ
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
# 肤色修饰符 + 变体选择器
_EMOJI_MOD = "[\U0001F3FB-\U0001F3FF\uFE0E\uFE0F]"

_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF]{2}"            # 旗帜序列
    "|[0-9#*]\uFE0F?\u20E3"                 # 按键序列
    "|(?:" + _EMOJI_BASE_CHARS +
    _EMOJI_MOD + "*"                         # 可选肤色/变体
    "(?:\u200D" + _EMOJI_BASE_CHARS +        # ZWJ 链
    _EMOJI_MOD + "*)*)"
)

# ── 段落类型常量 ──
SEG_TEXT = 'text'        # 普通文字（主字体）
SEG_LINK = 'link'        # @提及 或 URL（主字体，蓝色）
SEG_LINK_TEXT = 'link_text'  # 链接文本（主字体，蓝色）
SEG_EMOTE = 'emote'      # B 站表情包（图片）
SEG_EMOJI = 'emoji'      # Unicode emoji（emoji 字体）
SEG_UNICODE = 'unicode'  # 其他主字体缺失的符号（回退字体）


class LinkInfo:
    """链接段落信息：携带原文、显示标题、前缀图标"""
    __slots__ = ('raw', 'title', 'prefix_icon')
    def __init__(self, raw: str, title: str = "", prefix_icon: str = ""):
        self.raw = raw
        self.title = title or raw
        self.prefix_icon = prefix_icon


Segment = tuple[str, str | EmoteInfo | LinkInfo]


# 肌肤色修饰符正则：用于去除 emoji 肤色
_SKIN_TONE_RE = re.compile('[\U0001F3FB-\U0001F3FF]')


def _draw_text_with_fallback(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fill,
    font: ImageFont.FreeTypeFont,
    canvas: Image.Image | None = None,
) -> float:
    """绘制文本，自动使用 emoji 字体和回退字体。返回占用横向宽度。"""
    fc = _get_font_config(int(font.size))
    x, y = xy
    cx = 0.0

    # 按 emoji 序列切分，分别使用 emoji 字体渲染
    last_end = 0
    for match in _EMOJI_RE.finditer(text):
        if match.start() > last_end:
            seg = text[last_end:match.start()]
            cx += _draw_plain_text(draw, (x + cx, y), seg, fill, fc)
        emoji_text = match.group()
        draw.text((x + cx, y+EMOJI_TEXT_OFFSET), emoji_text, fill=fill, font=fc.emoji, embedded_color=True)
        cx += fc.emoji.getlength(emoji_text)
        last_end = match.end()

    if last_end < len(text):
        seg = text[last_end:]
        cx += _draw_plain_text(draw, (x + cx, y), seg, fill, fc)

    return cx


def _draw_plain_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fill,
    fc: FontConfig,
) -> float:
    """绘制非 emoji 文本，主字体缺失时使用回退字体"""
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
    """加载字体，优先使用 assets 目录下的 LXGW 文楷等宽"""
    if _MAIN_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(_MAIN_FONT_PATH), size)
        except Exception:
            pass

FONT_TITLE = _find_font(36, bold=True)
FONT_BODY = _find_font(28, bold=True)
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
    # _rounded_rectangle(draw, (x, y, x + tw + pad_x * 2, y + th + pad_y * 2), radius, bg_color)
    draw.text((x + pad_x, y + pad_y -3), text, fill=bg_color, font=font)
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


def _draw_stat_item(draw: ImageDraw.ImageDraw, x: int, y: int, item_width: int, label: str, value: str) -> int:
    """绘制单个统计项: 数值 + 标签, 返回占用宽度"""
    # 数值
    val_w = FONT_STAT_VALUE.getlength(value)
    draw.text((x+item_width//2 - val_w//2, y), value, fill=COLOR_STAT_VALUE, font=FONT_STAT_VALUE)
    # 标签
    label_bbox = FONT_STAT_LABEL.getbbox(label)
    label_w = label_bbox[2] - label_bbox[0]
    draw.text((x+item_width//2 - label_w//2, y + 42), label, fill=COLOR_STAT_LABEL, font=FONT_STAT_LABEL)
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
        draw = ImageDraw.Draw(mask)
        draw.circle((size//2, size//2), size//2, fill=255)
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


def _split_by_emotes(message: str, emotes: dict[str, EmoteInfo]) -> list[Segment]:
    """按 B 站表情包切分消息"""
    if not emotes:
        return [(SEG_TEXT, message)]

    sorted_keys = sorted(emotes.keys(), key=len, reverse=True)
    pattern = '|'.join(re.escape(key) for key in sorted_keys)

    segments: list[Segment] = []
    last_end = 0
    for match in re.finditer(pattern, message):
        if match.start() > last_end:
            segments.append((SEG_TEXT, message[last_end:match.start()]))
        segments.append((SEG_EMOTE, emotes[match.group()]))
        last_end = match.end()
    if last_end < len(message):
        segments.append((SEG_TEXT, message[last_end:]))

    return segments if segments else [(SEG_TEXT, message)]


def _split_by_links(
    segments: list[Segment],
    at_names: dict[str, int] | None,
    jump_urls: dict[str, JumpUrlInfo] | None = None,
) -> list[Segment]:
    """在 text 段落中识别 @提及、URL 和 jump_url 关键词，标记为 link"""
    parts: list[str] = []
    if at_names:
        sorted_names = sorted(at_names.keys(), key=len, reverse=True)
        parts.append('(?:' + '|'.join(re.escape(f'@{n}') for n in sorted_names) + ')')
    parts.append(r'https?://[^\s\u3000<>\[\]\u300c\u300d\u3010\u3011\uff09)]+')
    combined = re.compile('|'.join(parts))

    result: list[Segment] = []
    for seg_type, seg_data in segments:
        if seg_type != SEG_TEXT:
            result.append((seg_type, seg_data))
            continue
        last_end = 0
        found = False
        for match in combined.finditer(seg_data):
            found = True
            if match.start() > last_end:
                result.append((SEG_TEXT, seg_data[last_end:match.start()]))
            raw = match.group()
            # 查找 jump_url 信息
            jinfo = jump_urls.get(raw) if jump_urls else None
            if jinfo:
                result.append((SEG_LINK, LinkInfo(raw, jinfo.title, jinfo.prefix_icon)))
            else:
                result.append((SEG_LINK, LinkInfo(raw)))
            last_end = match.end()
        if last_end < len(seg_data):
            result.append((SEG_TEXT, seg_data[last_end:]))
        elif not found:
            result.append((SEG_TEXT, seg_data))
    return result


def _split_by_emoji(segments: list[Segment]) -> list[Segment]:
    """在 text 段落中识别 emoji 序列，并去除肤色修饰符"""
    result: list[Segment] = []
    for seg_type, seg_data in segments:
        if seg_type != SEG_TEXT:
            result.append((seg_type, seg_data))
            continue
        last_end = 0
        found = False
        for match in _EMOJI_RE.finditer(seg_data):
            found = True
            if match.start() > last_end:
                result.append((SEG_TEXT, seg_data[last_end:match.start()]))
            # 去除肤色修饰符，渲染默认黄皮肤 emoji
            emoji_text = _SKIN_TONE_RE.sub('', match.group())
            if emoji_text:
                result.append((SEG_EMOJI, emoji_text))
            last_end = match.end()
        if last_end < len(seg_data):
            result.append((SEG_TEXT, seg_data[last_end:]))
        elif not found:
            result.append((SEG_TEXT, seg_data))
    return result


def _split_by_font_coverage(segments: list[Segment], main_font: ImageFont.FreeTypeFont) -> list[Segment]:
    """将 text 段落中主字体无法渲染的字符标记为 unicode"""
    result: list[Segment] = []
    for seg_type, seg_data in segments:
        if seg_type != SEG_TEXT:
            result.append((seg_type, seg_data))
            continue
        cur_type = None
        cur_text = ""
        for ch in seg_data:
            ch_type = SEG_UNICODE if ord(ch) > 127 and _is_tofu(ch, main_font) else SEG_TEXT
            if ch_type == cur_type:
                cur_text += ch
            else:
                if cur_text:
                    result.append((cur_type, cur_text))
                cur_type = ch_type
                cur_text = ch
        if cur_text:
            result.append((cur_type, cur_text))
    return result


def _parse_message_segments(
    message: str,
    emotes: dict[str, EmoteInfo],
    at_names: dict[str, int] | None = None,
    jump_urls: dict[str, JumpUrlInfo] | None = None,
    font_config: FontConfig | None = None,
) -> list[Segment]:
    """将评论消息解析为 text / link / emote / emoji / unicode 段落列表"""
    segments = _split_by_emotes(message, emotes)
    segments = _split_by_links(segments, at_names, jump_urls)
    segments = _split_by_emoji(segments)
    if font_config:
        segments = _split_by_font_coverage(segments, font_config.main)
    return segments


def _wrap_message_segments(
    segments: list[Segment],
    font_config: FontConfig,
    max_width: int,
    max_lines: int = 6,
    emote_size: int = 30,
) -> tuple[list[list[Segment]], int]:
    """将混合段落列表按宽度换行"""
    lines: list[list[Segment]] = []
    current_line: list[Segment] = []
    current_width = 0.0
    mapped_segments = []
    for segment in segments:
        if segment[0] == SEG_LINK:
            link_info = segment[1]
            if link_info.prefix_icon:
                mapped_segments.append((SEG_EMOTE, EmoteInfo(text="url", url=link_info.prefix_icon)))
            mapped_segments.append((SEG_LINK_TEXT, link_info.title))
        else:
            mapped_segments.append(segment)

    def _flush_line():
        nonlocal current_line, current_width
        lines.append(current_line)
        current_line = []
        current_width = 0.0
    
    def _remaing_chars_count(idx, text_discount=0):
        count = - text_discount
        for seg_type, seg_data in segments[idx:]:
            if seg_type == SEG_EMOTE or seg_type == SEG_EMOJI:
                count += 1
            elif seg_type == SEG_LINK_TEXT:
                count += len(seg_data)
            else:
                count += len(seg_data)
        return count

    for idx, (seg_type, seg_data) in enumerate(mapped_segments):
        if seg_type == SEG_EMOTE:
            w = emote_size + 2
            if current_width + w > max_width and current_line:
                _flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaing_chars_count(idx)
            current_line.append((SEG_EMOTE, seg_data))
            current_width += w
        elif seg_type == SEG_EMOJI:
            w = font_config.emoji.getlength(seg_data)
            if current_width + w > max_width and current_line:
                _flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaing_chars_count(idx)
            current_line.append((SEG_EMOJI, seg_data))
            current_width += w
        else:  # SEG_TEXT, SEG_UNICODE, SEG_LINK_TEXT
            font = font_config.fallback if seg_type == SEG_UNICODE else font_config.main
            for i, ch in enumerate(seg_data):
                if ch == '\n':
                    _flush_line()
                    if len(lines) >= max_lines:
                        return lines, _remaing_chars_count(idx, len(seg_data) - i)
                    continue
                ch_w = font.getlength(ch)
                if current_width + ch_w > max_width and current_line:
                    _flush_line()
                    if len(lines) >= max_lines:
                        return lines, _remaing_chars_count(idx, len(seg_data) - i)
                if current_line and current_line[-1][0] == seg_type:
                    current_line[-1] = (seg_type, current_line[-1][1] + ch)
                else:
                    current_line.append((seg_type, ch))
                current_width += ch_w

    if current_line:
        if len(lines) < max_lines:
            lines.append(current_line)

    return (lines, 0) if lines else ([[(SEG_TEXT, '')]], 0)


def _draw_message_with_emotes(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    wrapped_lines: list[list[Segment]],
    x: int,
    y: int,
    font_config: FontConfig,
    line_height: int,
    emote_size: int,
    text_color: tuple | None = None,
) -> int:
    """绘制包含表情包的消息文本，返回占用的总高度"""
    if text_color is None:
        text_color = COLOR_MESSAGE
    total_h = 0
    for line_segments in wrapped_lines:
        cx = x
        for seg_type, seg_data in line_segments:
            if seg_type == SEG_TEXT or seg_type == SEG_LINK_TEXT:
                color = COLOR_LINK if seg_type == SEG_LINK_TEXT else text_color
                text_y = y + (line_height - font_config.main.size) // 2
                draw.text((cx, text_y), seg_data, fill=color, font=font_config.main)
                cx += int(font_config.main.getlength(seg_data))
            elif seg_type == SEG_LINK:
                link_text = seg_data
                text_y = y + (line_height - font_config.main.size) // 2
                draw.text((cx, text_y), link_text, fill=COLOR_LINK, font=font_config.main)
                cx += int(font_config.main.getlength(link_text))
            elif seg_type == SEG_EMOJI:
                emoji_y = y + (line_height - font_config.emoji.size) // 2 + EMOJI_TEXT_OFFSET
                draw.text((cx, emoji_y), seg_data, fill=text_color, font=font_config.emoji, embedded_color=True)
                cx += int(font_config.emoji.getlength(seg_data))
            elif seg_type == SEG_UNICODE:
                unicode_y = y + (line_height - font_config.fallback.size) // 2
                draw.text((cx, unicode_y), seg_data, fill=text_color, font=font_config.fallback)
                cx += int(font_config.fallback.getlength(seg_data))
            elif seg_type == SEG_EMOTE:
                emote_img = _load_emote(seg_data.url, emote_size)
                if emote_img:
                    emote_y = y + (line_height - emote_size) // 2
                    canvas.paste(emote_img, (int(cx), int(emote_y)), emote_img)
                    cx += emote_size + 1
                else:
                    text_y = y + (line_height - font_config.main.size) // 2
                    draw.text((cx, text_y), seg_data.text, fill=text_color, font=font_config.main)
                    cx += int(font_config.main.getlength(seg_data.text))
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

    布局策略:
    - 弹幕少时：均匀分散到整个可用垂直空间，行间距自适应拉大
    - 弹幕多时：先尝试无重叠放置，放不下时允许轻微 y 偏移溢出
    - 同行弹幕在水平方向上尽量不重叠（贪心区间检测）
    """
    if not danmaku_list:
        return cover

    overlay = cover.copy().convert("RGBA")
    txt_layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    cover_w, cover_h = overlay.size
    font = FONT_DANMAKU
    min_line_height = 36       # 最小行高
    margin_top = 5
    margin_bottom = 45         # 底部留出空间给时长标签
    available_h = cover_h - margin_top - margin_bottom

    n = len(danmaku_list)
    rng = random.Random(42)    # 固定种子保证可复现

    # ── 1. 计算每条弹幕的文字宽度 ──
    text_widths = [font.getlength(t) for t in danmaku_list]

    # ── 2. 确定行数与行高 ──
    # 最多可容纳的行数（按最小行高）
    max_possible_rows = max(1, available_h // min_line_height)
    # 实际使用的行数：不超过弹幕数，也不超过最大行数
    num_rows = min(n, max_possible_rows)
    # 自适应行高：弹幕少时均匀撑满整个可用区域
    line_height = available_h / num_rows if num_rows > 0 else min_line_height

    # ── 3. 将弹幕分配到行（尽量均匀） ──
    # 按每行一个桶，轮流放入，保证各行弹幕数量差 ≤ 1
    row_buckets: list[list[int]] = [[] for _ in range(num_rows)]
    for i in range(n):
        row_buckets[i % num_rows].append(i)

    # ── 4. 行内水平去重叠放置 ──
    # placed[i] = (x, y, w) 已放置弹幕的位置信息
    placed: list[tuple[float, float, float]] = [(0, 0, 0)] * n

    for row_idx, indices in enumerate(row_buckets):
        if not indices:
            continue
        row_y_center = margin_top + row_idx * line_height

        # 按文字宽度降序排列，大的先放，贪心更容易成功
        sorted_indices = sorted(indices, key=lambda i: text_widths[i], reverse=True)

        # 当前行已占用的水平区间列表 [(x_start, x_end), ...]
        occupied: list[tuple[float, float]] = []

        for idx in sorted_indices:
            tw = text_widths[idx]
            padding_x = 20  # 弹幕间最小水平间距

            # 尝试找到不重叠的 x 位置
            best_x = _find_non_overlapping_x(
                tw, cover_w, occupied, padding_x, rng
            )

            # y 方向加微小随机抖动，使同行弹幕不在完全相同的 y 上
            jitter_range = max(1, int(line_height * 0.15))
            y_jitter = rng.randint(-jitter_range, jitter_range)
            final_y = row_y_center + y_jitter
            # 确保不超出安全区域（允许少量溢出）
            final_y = max(margin_top - 5, min(final_y, margin_top + available_h - min_line_height + 5))

            placed[idx] = (best_x, final_y, tw)
            occupied.append((best_x - padding_x / 2, best_x + tw + padding_x / 2))

    # ── 5. 绘制所有弹幕 ──
    for i, text in enumerate(danmaku_list):
        x, y, _ = placed[i]
        ix, iy = int(x), int(y)

        # 描边效果：8 方向偏移画黑色文字
        stroke_offsets = [(-1, -1), (-1, 1), (1, -1), (1, 1),
                          (-2, 0), (2, 0), (0, -2), (0, 2)]
        for dx, dy in stroke_offsets:
            draw.text((ix + dx, iy + dy), text, fill=(0, 0, 0, 200), font=font)

        # 白色弹幕文字
        draw.text((ix, iy), text, fill=(255, 255, 255, 230), font=font)

    overlay = Image.alpha_composite(overlay, txt_layer)
    return overlay.convert("RGB")


def _find_non_overlapping_x(
    text_w: float,
    canvas_w: int,
    occupied: list[tuple[float, float]],
    padding: float,
    rng: random.Random,
) -> float:
    """在水平方向上寻找一个不与已有区间重叠的 x 位置。

    策略: 先收集所有空闲区间，从中随机选一个足够宽的区间放置；
    若没有足够宽的空闲区间，则选最宽的空闲区间居中放置（允许溢出）。
    """
    margin = 10
    total_w = canvas_w - margin * 2
    need_w = text_w

    if not occupied:
        # 没有已占用区间 → 随机放
        max_x = max(margin, int(canvas_w - text_w - margin))
        return float(rng.randint(margin, max(margin, max_x)))

    # 将已占用区间按左端排序
    sorted_occ = sorted(occupied, key=lambda seg: seg[0])

    # 构建空闲区间列表
    free_intervals: list[tuple[float, float]] = []
    prev_end = float(margin)
    for seg_start, seg_end in sorted_occ:
        if seg_start > prev_end:
            free_intervals.append((prev_end, seg_start))
        prev_end = max(prev_end, seg_end)
    # 右侧剩余
    right_limit = float(canvas_w - margin)
    if prev_end < right_limit:
        free_intervals.append((prev_end, right_limit))

    # 分为「足够宽」和「不够宽但可用」两类
    good: list[tuple[float, float]] = []
    fallback: list[tuple[float, float]] = []
    for a, b in free_intervals:
        width = b - a
        if width >= need_w:
            good.append((a, b))
        elif width > 0:
            fallback.append((a, b))

    if good:
        # 从足够宽的空闲区间中随机选一个，然后在区间内随机放置
        interval = rng.choice(good)
        lo = interval[0]
        hi = interval[1] - need_w
        return float(rng.randint(int(lo), max(int(lo), int(hi))))

    if fallback:
        # 选最宽的空闲区间，居中放置（会部分超出该区间，但比完全重叠好）
        best = max(fallback, key=lambda seg: seg[1] - seg[0])
        center = (best[0] + best[1]) / 2
        x = center - need_w / 2
        return max(float(margin), min(x, float(canvas_w - need_w - margin)))

    # 完全没有空闲空间 → 随机放
    max_x = max(margin, int(canvas_w - text_w - margin))
    return float(rng.randint(margin, max(margin, max_x)))

def _draw_logo(image: Image.Image, logo_path: str,  x: int, y: int, height: int) -> int:
    logo = Image.open(logo_path).convert("RGBA")
    # 等比缩放
    w, h = logo.size
    scale = height / h
    new_w = int(w * scale)
    logo = logo.resize((new_w, height), Image.Resampling.LANCZOS)
    image.paste(logo, (x, y), logo)
    return new_w

def _draw_copyright(draw: Image.Image, canvas: ImageDraw.ImageDraw, x: int, y: int):
    text = "Made by"
    draw.text((x, y), text, fill=COLOR_STAT_LABEL, font=FONT_SMALL)
    text_w = FONT_SMALL.getlength(text)
    x += int(text_w) + 5
    logo_w = _draw_logo(canvas, "assets/logo.png", x, y-2, 32)
    text = "WoofZJ"
    x += logo_w + 5
    draw.text((x, y), text, fill=(255, 0, 0), font=FONT_SMALL)
    text_w = FONT_SMALL.getlength(text)
    x += int(text_w)

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

    title_lines = _wrap_text(video.title, FONT_TITLE, content_width, max_lines=5)
    title_line_height = 48
    title_height = len(title_lines) * title_line_height
    total_height = CARD_HEIGHT_BASE + title_height

    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), (0, 0, 0, 0))

    # fill background
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, CARD_WIDTH, total_height), fill=(255, 255, 255))

    # draw cover
    if download_cover and video.cover:
        cover = _load_cover(video.cover)
        if danmaku_list:
            cover = _draw_danmaku_on_cover(cover, danmaku_list)
    else:
        cover = _create_placeholder_cover()
    cover_rgba = cover.convert("RGBA")
    canvas.paste(cover_rgba, (0, 0), cover_rgba)

    # draw duration
    dur_text = video.duration_str
    dur_bbox = FONT_DURATION.getbbox(dur_text)
    dur_tw = dur_bbox[2] - dur_bbox[0]
    dur_th = dur_bbox[3] - dur_bbox[1]
    dur_pad_x, dur_pad_y = 12, 6
    dur_x = CARD_WIDTH - dur_tw - dur_pad_x * 2 - 16
    dur_y = COVER_HEIGHT - dur_th - dur_pad_y * 2 - 16
    dur_overlay = Image.new("RGBA", (dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), (0, 0, 0, 0))
    dur_draw = ImageDraw.Draw(dur_overlay)
    dur_draw.rectangle((0, 0, dur_tw + dur_pad_x * 2, dur_th + dur_pad_y * 2), fill=(0, 0, 0, 180))
    canvas.paste(dur_overlay, (dur_x, dur_y), dur_overlay)
    draw.text((dur_x + dur_pad_x, dur_y + dur_pad_y - 5), dur_text, fill=COLOR_DURATION_TEXT, font=FONT_DURATION)

    # draw title
    y_cursor = COVER_HEIGHT + LINE_GAP
    for line in title_lines:
        _draw_text_with_fallback(draw, (PADDING, y_cursor), line, fill=COLOR_TITLE, font=FONT_TITLE, canvas=canvas)
        y_cursor += title_line_height

    y_cursor += LINE_GAP

    # draw staffs
    # author face
    avatar = None
    if download_cover and video.author_face:
        avatar = _load_avatar(video.author_face, AVATAR_SIZE)
    if not avatar:
        avatar = _create_placeholder_avatar(AVATAR_SIZE)
    canvas.paste(avatar, (PADDING, y_cursor), avatar)
    # author name
    author_text = video.author_name
    text_y = y_cursor + (AVATAR_SIZE - FONT_BODY.size) // 2
    draw.text((PADDING + AVATAR_SIZE + PADDING, text_y), author_text, fill=COLOR_ACCENT, font=FONT_BODY)
    # draw other staffs
    staff_avatars = []
    for staff in video.staffs:
        if staff.mid == video.author_mid:
            continue
        staff_avatar = None
        if download_cover and staff.face:
            staff_avatar = _load_avatar(staff.face, AVATAR_SIZE)
        if not staff_avatar:
            staff_avatar = _create_placeholder_avatar(AVATAR_SIZE)
        staff_avatars.append(staff_avatar)
    left = PADDING * 3 + AVATAR_SIZE + FONT_BODY.getlength(author_text)
    if staff_avatars:
        draw.text((left, text_y), "+", fill=COLOR_DESC_TEXT, font=FONT_BODY)
        left += FONT_BODY.getlength("+") + PADDING
        right_text = f"联合投稿"
        right = FONT_BODY.getlength(right_text) + PADDING * 2
        remain_width = CARD_WIDTH - (left + right)
        if len(staff_avatars) > 1:
            gap = (remain_width - AVATAR_SIZE) // (len(staff_avatars)-1)
        else:
            gap = 0
        if gap > AVATAR_SIZE + PADDING:
            gap = AVATAR_SIZE + PADDING
        for staff_avatar in staff_avatars:
            canvas.paste(staff_avatar, (int(left), y_cursor), staff_avatar)
            left += gap
        left += AVATAR_SIZE - gap + PADDING
        draw.text((left, text_y), right_text, fill=COLOR_DESC_TEXT, font=FONT_BODY)
        left += FONT_BODY.getlength(right_text) + PADDING
    if left > 650:
        y_cursor += AVATAR_SIZE + LINE_GAP
        _draw_logo(canvas, "assets/bilibili.png", 720, y_cursor-5, FONT_SMALL.size + 10)
    else:
        _draw_logo(canvas, "assets/bilibili.png", 670, y_cursor + 5, AVATAR_SIZE - 10)
        y_cursor += AVATAR_SIZE + LINE_GAP

    # draw publish time, bvid, resolution
    res_text = video.resolution_str
    time_text = f"发布于 {video.publish_time_str} | {video.bvid} | 分辨率：{res_text}"
    draw.text((PADDING, y_cursor), time_text, fill=COLOR_DESC_TEXT, font=FONT_SMALL)
    y_cursor += FONT_SMALL.size + LINE_GAP + 4

    # draw divider
    draw.line((PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor), fill=COLOR_DIVIDER, width=2)
    y_cursor += LINE_GAP + 4

    # draw data snapshot time
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot_text = f"截止于 {snapshot_time} 的数据："
    snapshot_w = FONT_SMALL.getlength(snapshot_text)
    draw.text(((CARD_WIDTH - snapshot_w) / 2, y_cursor), snapshot_text, fill=COLOR_DESC_TEXT, font=FONT_SMALL)
    y_cursor += FONT_SMALL.size + LINE_GAP

    # draw stats
    stats = [
        ("播放", VideoInfo.format_count(video.view)),
        ("点赞", VideoInfo.format_count(video.like)),
        ("投币", VideoInfo.format_count(video.coin)),
        ("收藏", VideoInfo.format_count(video.favorite)),
        ("弹幕", VideoInfo.format_count(video.danmaku)),
        ("评论", VideoInfo.format_count(video.reply)),
        ("转发", VideoInfo.format_count(video.share)),
    ]
    item_width = content_width // len(stats)
    x = PADDING
    for label, value in stats:
        _draw_stat_item(draw, x, y_cursor, item_width, label, value)
        x += item_width
    y_cursor += 80

    _draw_copyright(draw, canvas, CARD_WIDTH // 2 - 100, y_cursor)

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
COLOR_COMMENT_HEADER_BG = (254, 213, 214)
COLOR_COMMENT_HEADER_TEXT = (34, 34, 34)
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
    name_line_h = 28 if is_sub else 30

    # 消息文本区域宽度
    text_left = avatar_size + 12
    text_width = content_width - text_left

    # 消息行数（考虑表情包宽度）
    msg_line_h = 30 if is_sub else 32
    emote_size = msg_line_h - 2
    fc = _get_font_config(int(font_msg.size))
    segments = _parse_message_segments(comment.message, comment.emotes, comment.at_names, comment.jump_urls, fc)
    wrapped, overflow_count = _wrap_message_segments(segments, fc, text_width, max_lines=6, emote_size=emote_size)
    msg_h = (len(wrapped) + (1 if overflow_count > 0 else 0)) * msg_line_h

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

    name_line_h = 28 if is_sub else 30
    y += name_line_h + 6

    # ── 评论内容（支持表情包、emoji、链接） ──
    msg_line_h = 30 if is_sub else 32
    emote_size = msg_line_h - 2
    fc = _get_font_config(int(font_msg.size))
    segments = _parse_message_segments(comment.message, comment.emotes, comment.at_names, comment.jump_urls, fc)
    wrapped, overflow_count = _wrap_message_segments(segments, fc, text_width, max_lines=6, emote_size=emote_size)
    msg_h = _draw_message_with_emotes(canvas, draw, wrapped, text_x, y, fc, msg_line_h, emote_size)
    y += msg_h
    if overflow_count > 0:
        overflow_text = f"...（省略 {overflow_count} 字符）"
        text_y = y + (msg_line_h - font_msg.size) / 2
        draw.text((text_x, text_y), overflow_text, fill=COLOR_OVERFLOW, font=font_msg)
        y += msg_line_h

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
    header_h = 50  # 顶部 "评论 (N)" 区域

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
    _rounded_rectangle(draw, (0, 0, COMMENT_CARD_WIDTH, header_h), 0, COLOR_COMMENT_HEADER_BG)
    logo_w = _draw_logo(canvas, "assets/bilibili.png", COMMENT_PADDING, (header_h-40) // 2, 40)
    _draw_logo(canvas, "assets/bilibili.png", COMMENT_CARD_WIDTH - COMMENT_PADDING - logo_w, (header_h-40) // 2, 40)
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
    y_cursor -= 18
    _draw_copyright(draw, canvas, COMMENT_CARD_WIDTH // 2 - 100, y_cursor)
    y_cursor += 30

    # 裁切到实际高度
    actual_h = y_cursor
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
