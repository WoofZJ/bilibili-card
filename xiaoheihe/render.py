import io
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from xiaoheihe.models import (
    XiaoheiheCommentItem,
    XiaoheiheCommentsData,
    XiaoheiheEmote,
    XiaoheiheImage,
    XiaoheihePostInfo,
)


CARD_WIDTH = 800
PADDING = 28
CONTENT_WIDTH = CARD_WIDTH - PADDING * 2
AVATAR_SIZE = 58
POST_COVER_HEIGHT = 420
ARTICLE_IMAGE_MAX_HEIGHT = 760

COMMENT_CARD_WIDTH = 800
COMMENT_PADDING = 20
COMMENT_AVATAR_SIZE = 48
COMMENT_SUB_AVATAR_SIZE = 36

COLOR_BG = (255, 255, 255)
COLOR_TITLE = (28, 32, 36)
COLOR_TEXT = (49, 54, 60)
COLOR_SUB = (112, 119, 128)
COLOR_LIGHT = (244, 246, 248)
COLOR_LINE = (232, 236, 240)
COLOR_ACCENT = (0, 188, 113)
COLOR_TAG_BG = (236, 249, 243)
COLOR_TAG_TEXT = (0, 132, 84)

COLOR_COMMENT_BG = (255, 255, 255)
COLOR_COMMENT_HEADER_BG = (224, 246, 237)
COLOR_COMMENT_HEADER_TEXT = (34, 34, 34)
COLOR_TOP_BADGE_BG = (255, 215, 0)
COLOR_TOP_BADGE_TEXT = (100, 70, 0)
COLOR_UP_BADGE_BG = (0, 188, 113)
COLOR_UP_BADGE_TEXT = (255, 255, 255)
COLOR_LEVEL_COLORS = {
    0: (191, 191, 191),
    1: (191, 191, 191),
    2: (149, 221, 178),
    3: (109, 192, 233),
    4: (255, 179, 76),
    5: (255, 108, 0),
    6: (255, 0, 0),
}
COLOR_LIKE_TEXT = (0xaa, 0x37, 0x31)
COLOR_TIME_TEXT = (153, 153, 153)
COLOR_REPLY_COUNT = (0, 132, 84)
COLOR_USERNAME = (51, 51, 51)
COLOR_MESSAGE = (34, 34, 34)
COLOR_SUB_LINE = (229, 233, 239)
COLOR_OVERFLOW = (120, 120, 120)

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_MAIN_FONT_PATH = _ASSETS_DIR / "LXGWWenKaiMono-Regular.ttf"
_EMOJI_FONT_PATH = _ASSETS_DIR / "seguiemj.ttf"
_FALLBACK_FONT_PATH = _ASSETS_DIR / "unifont.otf"


class FontConfig:
    def __init__(self, size: int):
        self.main = _load_font(_MAIN_FONT_PATH, size)
        self.emoji = _load_font(_EMOJI_FONT_PATH, size, self.main)
        self.fallback = _load_font(_FALLBACK_FONT_PATH, size, self.main)


_font_config_cache: dict[int, FontConfig] = {}


def _get_font_config(size: int) -> FontConfig:
    if size not in _font_config_cache:
        _font_config_cache[size] = FontConfig(size)
    return _font_config_cache[size]


def _load_font(path: Path, size: int, fallback=None):
    try:
        return ImageFont.truetype(str(path), size)
    except (OSError, IOError):
        return fallback or ImageFont.load_default()


FONT_BRAND = _load_font(_MAIN_FONT_PATH, 22)
FONT_TITLE = _load_font(_MAIN_FONT_PATH, 34)
FONT_BODY = _load_font(_MAIN_FONT_PATH, 25)
FONT_META = _load_font(_MAIN_FONT_PATH, 20)
FONT_SMALL = _load_font(_MAIN_FONT_PATH, 18)
FONT_COUNT = _load_font(_MAIN_FONT_PATH, 26)
FONT_COMMENT_NAME = _load_font(_MAIN_FONT_PATH, 22)
FONT_COMMENT = _load_font(_MAIN_FONT_PATH, 23)
FONT_COMMENT_HEADER = _load_font(_MAIN_FONT_PATH, 24)
FONT_COMMENT_USERNAME = _load_font(_MAIN_FONT_PATH, 24)
FONT_COMMENT_MESSAGE = _load_font(_MAIN_FONT_PATH, 24)
FONT_COMMENT_META = _load_font(_MAIN_FONT_PATH, 20)
FONT_COMMENT_BADGE = _load_font(_MAIN_FONT_PATH, 18)
FONT_COMMENT_SUB_USERNAME = _load_font(_MAIN_FONT_PATH, 22)
FONT_COMMENT_SUB_MESSAGE = _load_font(_MAIN_FONT_PATH, 22)
FONT_COMMENT_SUB_META = _load_font(_MAIN_FONT_PATH, 18)


_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|[\U0001F300-\U0001FAFF\U00002600-\U000027BF]\uFE0F?"
)
_XIAOHEIHE_EMOTE_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9]*_[^\[\]\s]{1,40}\]")

SEG_TEXT = "text"
SEG_EMOTE = "emote"


def _draw_text(draw: ImageDraw.ImageDraw, xy, text: str, fill, font):
    fc = _get_font_config(int(getattr(font, "size", 20)))
    x, y = xy
    cx = 0.0
    last_end = 0
    for match in _EMOJI_RE.finditer(text):
        if match.start() > last_end:
            seg = text[last_end:match.start()]
            draw.text((x + cx, y), seg, fill=fill, font=font)
            cx += font.getlength(seg)
        emoji = match.group()
        draw.text((x + cx, y + 4), emoji, fill=fill, font=fc.emoji, embedded_color=True)
        cx += fc.emoji.getlength(emoji)
        last_end = match.end()
    if last_end < len(text):
        seg = text[last_end:]
        draw.text((x + cx, y), seg, fill=fill, font=font)
        cx += font.getlength(seg)
    return cx


def _wrap_text(text: str, font, max_width: int, max_lines: int) -> tuple[list[str], int]:
    lines = []
    current = ""
    consumed = 0
    for ch in text:
        if ch == "\n":
            if current:
                lines.append(current)
                consumed += len(current) + 1
                current = ""
            if len(lines) >= max_lines:
                break
            continue
        test = current + ch
        if font.getlength(test) > max_width:
            if current:
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
    if len(lines) == max_lines and consumed < len(text) and lines:
        lines[-1] = _truncate(lines[-1], font, max_width)
    return lines or [""], max(len(text) - consumed, 0)


def _truncate(text: str, font, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    for idx in range(len(text), 0, -1):
        candidate = text[:idx].rstrip() + "..."
        if font.getlength(candidate) <= max_width:
            return candidate
    return "..."


def _format_count(value: int) -> str:
    return XiaoheihePostInfo.format_count(value)


def _load_remote_image(url: str, referer: str = "https://www.xiaoheihe.cn") -> Image.Image | None:
    if not url:
        return None
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": referer,
            },
            timeout=8,
        )
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


_emote_cache: dict[str, Image.Image | None] = {}


def _load_emote(emote: XiaoheiheEmote, size: int) -> Image.Image | None:
    cache_key = f"{emote.url}:{size}"
    if cache_key in _emote_cache:
        cached = _emote_cache[cache_key]
        return cached.copy() if cached else None

    img = _load_remote_image(emote.url)
    if img is None:
        _emote_cache[cache_key] = None
        return None

    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.paste(img, (x, y), img)
    _emote_cache[cache_key] = canvas
    return canvas.copy()


def _split_comment_segments(
    text: str,
    emotes: dict[str, XiaoheiheEmote] | None,
) -> list[tuple[str, str | XiaoheiheEmote]]:
    if not text:
        return [(SEG_TEXT, "")]
    if not emotes:
        return [(SEG_TEXT, text)]

    segments: list[tuple[str, str | XiaoheiheEmote]] = []
    last_end = 0
    for match in _XIAOHEIHE_EMOTE_RE.finditer(text):
        token = match.group()
        emote = emotes.get(token)
        if not emote:
            continue
        if match.start() > last_end:
            segments.append((SEG_TEXT, text[last_end:match.start()]))
        segments.append((SEG_EMOTE, emote))
        last_end = match.end()

    if last_end < len(text):
        segments.append((SEG_TEXT, text[last_end:]))
    return segments or [(SEG_TEXT, "")]


def _remaining_comment_chars(
    segments: list[tuple[str, str | XiaoheiheEmote]],
    start_idx: int,
    consumed_in_segment: int = 0,
) -> int:
    count = 0
    for idx, (seg_type, seg_data) in enumerate(segments[start_idx:], start=start_idx):
        if seg_type == SEG_EMOTE:
            count += 1
            continue
        text = str(seg_data)
        if idx == start_idx:
            count += max(len(text) - consumed_in_segment, 0)
        else:
            count += len(text)
    return count


def _wrap_comment_segments(
    text: str,
    emotes: dict[str, XiaoheiheEmote] | None,
    font,
    max_width: int,
    max_lines: int,
    emote_size: int,
) -> tuple[list[list[tuple[str, str | XiaoheiheEmote]]], int]:
    segments = _split_comment_segments(text, emotes)
    lines: list[list[tuple[str, str | XiaoheiheEmote]]] = []
    current_line: list[tuple[str, str | XiaoheiheEmote]] = []
    current_width = 0.0

    def flush_line():
        nonlocal current_line, current_width
        lines.append(current_line or [(SEG_TEXT, "")])
        current_line = []
        current_width = 0.0

    for idx, (seg_type, seg_data) in enumerate(segments):
        if seg_type == SEG_EMOTE:
            seg_width = emote_size + 2
            if current_width + seg_width > max_width and current_line:
                flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaining_comment_chars(segments, idx)
            current_line.append((SEG_EMOTE, seg_data))
            current_width += seg_width
            continue

        text = str(seg_data)
        for char_idx, char in enumerate(text):
            if char == "\n":
                flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaining_comment_chars(segments, idx, char_idx + 1)
                continue

            char_width = font.getlength(char)
            if current_width + char_width > max_width and current_line:
                flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaining_comment_chars(segments, idx, char_idx)

            if current_line and current_line[-1][0] == SEG_TEXT:
                current_line[-1] = (SEG_TEXT, str(current_line[-1][1]) + char)
            else:
                current_line.append((SEG_TEXT, char))
            current_width += char_width

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    return (lines, 0) if lines else ([[(SEG_TEXT, "")]], 0)


def _draw_comment_segments(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    lines: list[list[tuple[str, str | XiaoheiheEmote]]],
    x: int,
    y: int,
    font,
    line_height: int,
    emote_size: int,
    text_color,
) -> int:
    total_h = 0
    for line in lines:
        cx = x
        for seg_type, seg_data in line:
            if seg_type == SEG_EMOTE and isinstance(seg_data, XiaoheiheEmote):
                emote_img = _load_emote(seg_data, emote_size)
                emote_y = y + (line_height - emote_size) // 2
                if emote_img:
                    canvas.paste(emote_img, (int(cx), int(emote_y)), emote_img)
                else:
                    draw.rounded_rectangle(
                        (cx, emote_y, cx + emote_size, emote_y + emote_size),
                        radius=4,
                        fill=COLOR_LIGHT,
                        outline=COLOR_LINE,
                    )
                cx += emote_size + 2
                continue

            text_y = y + (line_height - font.size) / 2
            cx += _draw_text(draw, (cx, text_y), str(seg_data), text_color, font)
        y += line_height
        total_h += line_height
    return total_h


def _resize_image(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)


def _placeholder_image(width: int, height: int, text: str = "图片加载失败") -> Image.Image:
    img = Image.new("RGBA", (width, height), COLOR_LIGHT + (255,))
    draw = ImageDraw.Draw(img)
    tw = FONT_BODY.getlength(text)
    draw.text(((width - tw) / 2, height / 2 - 16), text, fill=COLOR_SUB, font=FONT_BODY)
    return img


def _load_avatar(url: str, size: int) -> Image.Image:
    img = _load_remote_image(url)
    if img is None:
        img = Image.new("RGBA", (size, size), (219, 225, 230, 255))
        d = ImageDraw.Draw(img)
        d.ellipse((size * 0.32, size * 0.18, size * 0.68, size * 0.54), fill=(158, 166, 176, 255))
        d.ellipse((size * 0.22, size * 0.52, size * 0.78, size * 1.05), fill=(158, 166, 176, 255))
    else:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _draw_tag(draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> int:
    label = f"#{text}"
    pad_x = 12
    pad_y = 6
    width = int(FONT_SMALL.getlength(label)) + pad_x * 2
    height = 30
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=COLOR_TAG_BG)
    draw.text((x + pad_x, y + pad_y - 1), label, fill=COLOR_TAG_TEXT, font=FONT_SMALL)
    return width


def _draw_brand(draw: ImageDraw.ImageDraw, x: int, y: int):
    draw.rounded_rectangle((x, y, x + 88, y + 32), radius=8, fill=(20, 24, 28))
    draw.text((x + 12, y + 4), "小黑盒", fill=(255, 255, 255), font=FONT_BRAND)


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
    draw.text((x, y), text, fill=COLOR_SUB, font=FONT_SMALL)
    x += int(FONT_SMALL.getlength(text)) + 5
    logo_w = _draw_logo(canvas, str(_ASSETS_DIR / "logo.png"), x, y - 4, 32)
    x += logo_w + 5
    draw.text((x, y), "WoofZJ", fill=(255, 0, 0), font=FONT_SMALL)


def render_post_card(post: XiaoheihePostInfo, download_images: bool = True) -> Image.Image:
    title_lines = _wrap_full_text(post.title, FONT_TITLE, CONTENT_WIDTH)
    tag_names = [topic.name for topic in post.topics if topic.name] + post.tags
    tag_names = list(dict.fromkeys(tag_names))[:4]

    title_h = len(title_lines) * 44
    blocks = post.blocks or [
        type("FallbackBlock", (), {"type": "text", "text": post.plain_text or post.description, "image": None})()
    ]
    measured_blocks = _measure_post_blocks(blocks)
    blocks_h = sum(item["height"] for item in measured_blocks)
    tags_h = 42 if tag_names else 0
    total_height = (
        PADDING + AVATAR_SIZE + 22 + title_h + 18 +
        blocks_h + tags_h + 110
    )

    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), COLOR_BG + (255,))
    draw = ImageDraw.Draw(canvas)
    y = PADDING

    avatar = _load_avatar(post.author.avatar, AVATAR_SIZE)
    canvas.paste(avatar, (PADDING, y), avatar)
    if post.author.username:
        name = post.author.username
    elif post.author.userid:
        name = f"用户 {post.author.userid}"
    else:
        name = "小黑盒用户"
    draw.text((PADDING + AVATAR_SIZE + 14, y + 4), _truncate(name, FONT_COMMENT_NAME, 420), fill=COLOR_TITLE, font=FONT_COMMENT_NAME)
    meta_parts = [post.create_time_str]
    if post.ip_location:
        meta_parts.append(f"IP {post.ip_location}")
    draw.text((PADDING + AVATAR_SIZE + 14, y + 34), " · ".join(part for part in meta_parts if part), fill=COLOR_SUB, font=FONT_META)
    if post.author.level:
        level_text = f"Lv.{post.author.level}"
        lx = CARD_WIDTH - PADDING - int(FONT_META.getlength(level_text)) - 18
        draw.rounded_rectangle((lx - 10, y + 14, CARD_WIDTH - PADDING, y + 42), radius=8, fill=COLOR_LIGHT)
        draw.text((lx, y + 17), level_text, fill=COLOR_SUB, font=FONT_META)
    y += AVATAR_SIZE + 22

    for line in title_lines:
        _draw_text(draw, (PADDING, y), line, COLOR_TITLE, FONT_TITLE)
        y += 44
    y += 10

    for block_info in measured_blocks:
        block = block_info["block"]
        if block.type == "text":
            for line in block_info["lines"]:
                _draw_text(draw, (PADDING, y), line, COLOR_TEXT, FONT_BODY)
                y += 36
            y += 14
        elif block.type == "image" and block.image:
            image_w, image_h = block_info["image_size"]
            image = _load_article_image(block.image, image_w, image_h) if download_images else None
            if image is None:
                image = _placeholder_image(image_w, image_h)
            image_x = PADDING + (CONTENT_WIDTH - image_w) // 2
            canvas.paste(image, (image_x, y), image)
            y += image_h + 20

    if tag_names:
        y += 8
        x = PADDING
        for tag in tag_names:
            width = _draw_tag(draw, x, y, tag)
            x += width + 8
            if x > CARD_WIDTH - PADDING - 120:
                break
        y += 42

    draw.line((PADDING, y, CARD_WIDTH - PADDING, y), fill=COLOR_LINE, width=1)
    y += 18
    stats = [
        ("评论", post.comment_num),
        ("点赞", post.up or post.favour_count),
        ("收藏", post.favour_count),
    ]
    stat_w = CONTENT_WIDTH // len(stats)
    for idx, (label, value) in enumerate(stats):
        sx = PADDING + idx * stat_w
        count = _format_count(value)
        cw = FONT_COUNT.getlength(count)
        lw = FONT_META.getlength(label)
        draw.text((sx + (stat_w - cw) / 2, y), count, fill=COLOR_TITLE, font=FONT_COUNT)
        draw.text((sx + (stat_w - lw) / 2, y + 34), label, fill=COLOR_SUB, font=FONT_META)
    
    y += 65
    _draw_copyright(draw, canvas, COMMENT_CARD_WIDTH // 2 - 80, y)

    return canvas


def _load_article_image(image: XiaoheiheImage, width: int, height: int) -> Image.Image | None:
    loaded = _load_remote_image(image.url)
    if loaded is None:
        return None
    return _resize_image(loaded, width, height)


def _wrap_full_text(text: str, font, max_width: int) -> list[str]:
    lines, _ = _wrap_text(text, font, max_width, max_lines=10000)
    return lines


def _article_image_size(image: XiaoheiheImage) -> tuple[int, int]:
    src_w = image.width or CONTENT_WIDTH
    src_h = image.height or POST_COVER_HEIGHT
    if src_w <= 0 or src_h <= 0:
        return CONTENT_WIDTH, POST_COVER_HEIGHT
    scale = min(CONTENT_WIDTH / src_w, ARTICLE_IMAGE_MAX_HEIGHT / src_h)
    return max(1, int(src_w * scale)), max(1, int(src_h * scale))


def _measure_post_blocks(blocks) -> list[dict]:
    measured = []
    for block in blocks:
        if block.type == "text":
            text = (block.text or "").strip()
            if not text:
                continue
            lines = _wrap_full_text(text, FONT_BODY, CONTENT_WIDTH)
            measured.append({
                "block": block,
                "lines": lines,
                "height": len(lines) * 36 + 14,
            })
        elif block.type == "image" and block.image and block.image.url:
            image_size = _article_image_size(block.image)
            measured.append({
                "block": block,
                "image_size": image_size,
                "height": image_size[1] + 20,
            })
    return measured


def render_post_to_bytes(post: XiaoheihePostInfo, fmt: str = "PNG") -> bytes:
    img = render_post_card(post)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _draw_level_badge(draw: ImageDraw.ImageDraw, x: int, y: int, level: int) -> int:
    color = COLOR_LEVEL_COLORS.get(level, (191, 191, 191))
    text = f"Lv{level}"
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 4
    draw.rounded_rectangle((x, y, x + tw + pad_x * 2, y + th + pad_y * 2), radius=4, fill=color)
    draw.text((x + pad_x, y + pad_y - 5), text, fill=(255, 255, 255), font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _draw_small_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, bg_color, text_color) -> int:
    bbox = FONT_COMMENT_BADGE.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 6, 3
    draw.rounded_rectangle((x, y, x + tw + pad_x * 2, y + th + pad_y * 2), radius=4, fill=bg_color)
    draw.text((x + pad_x, y + pad_y - 2), text, fill=text_color, font=FONT_COMMENT_BADGE)
    return tw + pad_x * 2


def _measure_comment_height(
    comment: XiaoheiheCommentItem,
    content_width: int,
    is_sub: bool = False,
    root_user_id: int = 0,
    emotes: dict[str, XiaoheiheEmote] | None = None,
) -> int:
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE
    name_line_h = 24 if is_sub else 30
    text_left = avatar_size + 12
    text_width = content_width - text_left
    msg_line_h = 28 if is_sub else 32
    emote_size = 26 if is_sub else 30
    lines, overflow_count = _wrap_comment_segments(
        _display_comment_text(comment, is_sub=is_sub, root_user_id=root_user_id),
        emotes,
        font_msg,
        text_width,
        max_lines=6,
        emote_size=emote_size,
    )
    msg_h = (len(lines) + (1 if overflow_count > 0 else 0)) * msg_line_h
    meta_h = 26 if is_sub else 30
    gap_after_name = 3 if is_sub else 6
    gap_after_msg = 4 if is_sub else 8
    bottom_gap = 6 if is_sub else 12
    height = name_line_h + gap_after_name + msg_h + gap_after_msg + meta_h + bottom_gap
    return max(height, avatar_size + 16)


def _display_comment_text(comment: XiaoheiheCommentItem, is_sub: bool = False, root_user_id: int = 0) -> str:
    if is_sub and root_user_id and comment.reply_user_id == root_user_id:
        return comment.text
    if comment.reply_user and comment.reply_user.username:
        return f"回复 @{comment.reply_user.username}: {comment.text}"
    return comment.text


def _draw_single_comment(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    comment: XiaoheiheCommentItem,
    x: int,
    y: int,
    content_width: int,
    is_sub: bool = False,
    root_user_id: int = 0,
    emotes: dict[str, XiaoheiheEmote] | None = None,
) -> int:
    avatar_size = COMMENT_SUB_AVATAR_SIZE if is_sub else COMMENT_AVATAR_SIZE
    font_username = FONT_COMMENT_SUB_USERNAME if is_sub else FONT_COMMENT_USERNAME
    font_msg = FONT_COMMENT_SUB_MESSAGE if is_sub else FONT_COMMENT_MESSAGE
    font_meta = FONT_COMMENT_SUB_META if is_sub else FONT_COMMENT_META
    start_y = y

    avatar = _load_avatar(comment.user.avatar, avatar_size)
    canvas.paste(avatar, (x, y), avatar)

    text_x = x + avatar_size + 12
    text_width = content_width - avatar_size - 12
    name_y = y + 2
    badge_x = text_x

    if comment.is_link_owner:
        w = _draw_small_badge(draw, badge_x, name_y + 3, "作者", COLOR_UP_BADGE_BG, COLOR_UP_BADGE_TEXT)
        badge_x += w + 6

    name = comment.user.username or (f"用户 {comment.user.userid}" if comment.user.userid else "小黑盒用户")
    uname_display = _truncate(name, font_username, text_width - (badge_x - text_x) - 120)
    draw.text((badge_x, name_y), uname_display, fill=COLOR_USERNAME, font=font_username)
    badge_x += int(font_username.getlength(uname_display)) + 8

    if comment.user.level:
        w = _draw_level_badge(draw, badge_x, name_y + 5, comment.user.level)
        badge_x += w + 6

    worn_medal = next((m for m in comment.user.medals if m.wear and m.name), None)
    if worn_medal and not is_sub:
        medal_text = _truncate(worn_medal.name, FONT_COMMENT_BADGE, 84)
        _draw_small_badge(draw, badge_x, name_y + 3, medal_text, COLOR_LIGHT, COLOR_SUB)

    name_line_h = 26 if is_sub else 30
    gap_after_name = 3 if is_sub else 6
    y += name_line_h + gap_after_name

    msg_line_h = 28 if is_sub else 32
    emote_size = 26 if is_sub else 30
    lines, overflow_count = _wrap_comment_segments(
        _display_comment_text(comment, is_sub=is_sub, root_user_id=root_user_id),
        emotes,
        font_msg,
        text_width,
        max_lines=6,
        emote_size=emote_size,
    )
    y += _draw_comment_segments(
        canvas,
        draw,
        lines,
        text_x,
        y,
        font_msg,
        msg_line_h,
        emote_size,
        COLOR_MESSAGE,
    )
    if overflow_count > 0:
        overflow_text = f"...（省略 {overflow_count} 字符）"
        draw.text((text_x, y + (msg_line_h - font_msg.size) / 2), overflow_text, fill=COLOR_OVERFLOW, font=font_msg)
        y += msg_line_h

    y += 4 if is_sub else 8

    meta_x = text_x
    like_text = f"{_format_count(comment.up)}赞"
    draw.text((meta_x, y), like_text, fill=COLOR_LIKE_TEXT, font=font_meta)
    meta_x += int(font_meta.getlength(like_text)) + 20

    meta_parts = []
    if comment.floor_num:
        meta_parts.append(f"#{comment.floor_num}")
    if comment.create_time_str:
        meta_parts.append(comment.create_time_str)
    if comment.ip_location:
        meta_parts.append(f"IP {comment.ip_location}")
    if meta_parts:
        meta_text = " · ".join(meta_parts)
        draw.text((meta_x, y), meta_text, fill=COLOR_TIME_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(meta_text)) + 20

    if comment.child_num > 0 and not is_sub:
        reply_text = f"{comment.child_num}条回复"
        draw.text((meta_x, y), reply_text, fill=COLOR_REPLY_COUNT, font=font_meta)

    meta_h = 26 if is_sub else 30
    y += meta_h + (6 if is_sub else 12)
    return y - start_y


def render_comments_card(comments_data: XiaoheiheCommentsData, max_comments: int = 4) -> Image.Image:
    comments = sorted(comments_data.comments, key=lambda item: item.up, reverse=True)[:min(max_comments, 4)]
    emotes = comments_data.emotes or {}
    content_width = COMMENT_CARD_WIDTH - COMMENT_PADDING * 2
    header_h = 50

    total_height = header_h + COMMENT_PADDING
    for comment in comments:
        total_height += _measure_comment_height(comment, content_width, emotes=emotes)
        for sub in comment.sub_comments[:2]:
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12
            total_height += _measure_comment_height(
                sub,
                sub_width,
                is_sub=True,
                root_user_id=comment.user.userid,
                emotes=emotes,
            )
        total_height += 12
    total_height += 30

    canvas = Image.new("RGBA", (COMMENT_CARD_WIDTH, total_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((0, 0, COMMENT_CARD_WIDTH, total_height), radius=0, fill=COLOR_COMMENT_BG + (255,))
    draw.rounded_rectangle((0, 0, COMMENT_CARD_WIDTH, header_h), radius=0, fill=COLOR_COMMENT_HEADER_BG)

    logo_path = str(_ASSETS_DIR / "xiaoheihe.png")
    logo_w = _draw_logo(canvas, logo_path, COMMENT_PADDING, (header_h - 40) // 2, 40)
    _draw_logo(canvas, logo_path, COMMENT_CARD_WIDTH - COMMENT_PADDING - logo_w, (header_h - 40) // 2, 40)
    header_text = f"热门评论 ({comments_data.total})"
    header_tw = FONT_COMMENT_HEADER.getlength(header_text)
    header_h_text = FONT_COMMENT_HEADER.getbbox(header_text)[3]
    draw.text(
        ((COMMENT_CARD_WIDTH - header_tw) / 2, (header_h - header_h_text) / 2),
        header_text,
        fill=COLOR_COMMENT_HEADER_TEXT,
        font=FONT_COMMENT_HEADER,
    )

    y_cursor = header_h + COMMENT_PADDING

    for idx, comment in enumerate(comments):
        height = _draw_single_comment(
            canvas,
            draw,
            comment,
            COMMENT_PADDING,
            y_cursor,
            content_width,
            emotes=emotes,
        )
        y_cursor += height

        if comment.sub_comments:
            sub_x = COMMENT_PADDING + COMMENT_AVATAR_SIZE + 12
            sub_width = content_width - COMMENT_AVATAR_SIZE - 12
            line_x = sub_x - 6
            sub_start_y = y_cursor

            for sub in comment.sub_comments[:2]:
                sub_h = _draw_single_comment(
                    canvas,
                    draw,
                    sub,
                    sub_x,
                    y_cursor,
                    sub_width,
                    is_sub=True,
                    root_user_id=comment.user.userid,
                    emotes=emotes,
                )
                y_cursor += sub_h

            draw.line((line_x, sub_start_y, line_x, y_cursor - 16), fill=COLOR_SUB_LINE, width=2)

        if idx < len(comments) - 1:
            draw.line(
                (COMMENT_PADDING, y_cursor, COMMENT_CARD_WIDTH - COMMENT_PADDING, y_cursor),
                fill=COLOR_LINE,
                width=1,
            )
            y_cursor += 12

    _draw_copyright(draw, canvas, COMMENT_CARD_WIDTH // 2 - 80, y_cursor)
    y_cursor += 30

    if y_cursor < total_height:
        canvas = canvas.crop((0, 0, COMMENT_CARD_WIDTH, y_cursor))

    return canvas.convert("RGB")


def render_comments_to_bytes(comments_data: XiaoheiheCommentsData, fmt: str = "PNG", max_comments: int = 4) -> bytes:
    img = render_comments_card(comments_data, max_comments=max_comments)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    buf.seek(0)
    return buf.getvalue()
