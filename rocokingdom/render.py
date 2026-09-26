import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

import random
from rocokingdom.models import RocoMerchantItem, RocoMerchantResult


CARD_WIDTH = 800
PADDING = 28
CONTENT_WIDTH = CARD_WIDTH - PADDING * 2
ITEM_IMAGE_SIZE = 96
SHIPPED_ITEM_IMAGE_SIZE = 64
ITEM_GAP = 16

COLOR_BG = (255, 255, 255)
COLOR_PANEL = (247, 250, 246)
COLOR_PANEL_ALT = (255, 250, 239)
COLOR_TITLE = (38, 45, 39)
COLOR_TEXT = (50, 57, 52)
COLOR_SUB = (112, 122, 112)
COLOR_MUTED = (150, 156, 148)
COLOR_LINE = (226, 232, 224)
COLOR_ACCENT = (48, 143, 93)
COLOR_ACCENT_DARK = (25, 101, 65)
COLOR_BADGE_BG = (224, 244, 232)
COLOR_EMPTY_BG = (247, 245, 240)
COLOR_PRICE = (173, 101, 33)
COLOR_VALUABLE = (255, 180, 180)

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_MAIN_FONT_PATH = _ASSETS_DIR / "LXGWWenKaiMono-Regular.ttf"
_FALLBACK_FONT_PATH = _ASSETS_DIR / "unifont.otf"


def _load_font(path: Path, size: int, fallback=None):
    try:
        return ImageFont.truetype(str(path), size)
    except (OSError, IOError):
        return fallback or ImageFont.load_default()


FONT_HERO = _load_font(_MAIN_FONT_PATH, 38)
FONT_TITLE = _load_font(_MAIN_FONT_PATH, 30)
FONT_BODY = _load_font(_MAIN_FONT_PATH, 24)
FONT_META = _load_font(_MAIN_FONT_PATH, 21)
FONT_TIME = _load_font(_MAIN_FONT_PATH, 22)
FONT_SMALL = _load_font(_MAIN_FONT_PATH, 18)
FONT_BADGE = _load_font(_MAIN_FONT_PATH, 20)
FONT_ITEM = _load_font(_MAIN_FONT_PATH, 28)
FONT_FALLBACK = _load_font(_FALLBACK_FONT_PATH, 24, FONT_BODY)


def render_merchant_card(result: RocoMerchantResult, download_images: bool = True) -> Image.Image:
    canvas = Image.new("RGBA", (CARD_WIDTH, 1000), COLOR_BG)
    draw = ImageDraw.Draw(canvas)

    y = 0
    _draw_info_panel(draw, canvas, result, y, download_images)
    y += 76
    y += PADDING

    full_time_items = list(result.rounds.get(0, []))
    current_items = [item for item in result.items if item.round != 0]
    if current_items:
        if len(current_items) <= 2:
            for item in current_items:
                _draw_item(canvas, draw, item, PADDING, y, CARD_WIDTH - PADDING * 2, download_images=download_images)
                y += 120 + ITEM_GAP
        else:
            for idx, item in enumerate(current_items):
                if idx % 2 == 1:
                    x = CARD_WIDTH // 2 + ITEM_GAP // 2
                else:
                    x = PADDING
                _draw_item(canvas, draw, item, x, y, CARD_WIDTH // 2 - PADDING - ITEM_GAP // 2, download_images=download_images)
                if idx % 2 == 1 or idx == len(current_items) - 1:
                    y += 120 + ITEM_GAP
    elif not full_time_items:
        _draw_empty_state(draw, result, PADDING, y)
        y += 120 + ITEM_GAP

    past_rounds = [
        (round_no, items)
        for round_no, items in result.rounds.items()
        if round_no > 0
        and items
        and (result.round is None or round_no < result.round)
    ]
    if full_time_items or past_rounds:
        if full_time_items and past_rounds:
            separate_text = "全时段及过往轮次商品"
        elif full_time_items:
            separate_text = "全时段商品"
        else:
            separate_text = "过往轮次商品"
        separate_text_w = FONT_BODY.getlength(separate_text)
        draw.line((PADDING, y + FONT_BODY.size // 2, (CARD_WIDTH - PADDING - separate_text_w)//2, y + FONT_BODY.size // 2), fill=COLOR_LINE, width=2)
        draw.line(((CARD_WIDTH + PADDING + separate_text_w)//2, y + FONT_BODY.size // 2, CARD_WIDTH - PADDING, y + FONT_BODY.size // 2), fill=COLOR_LINE, width=2)
        draw.text((CARD_WIDTH // 2 - separate_text_w // 2, y), separate_text, fill=COLOR_SUB, font=FONT_BODY)
        y += FONT_BODY.size + ITEM_GAP
        if full_time_items:
            _draw_shipped_items(canvas, draw, 0, full_time_items, PADDING, y, CARD_WIDTH - PADDING * 2, download_images=download_images)
            y += 24 + SHIPPED_ITEM_IMAGE_SIZE + ITEM_GAP
        for round_no, items in sorted(past_rounds, reverse=True):
            _draw_shipped_items(canvas, draw, round_no, items, PADDING, y, CARD_WIDTH - PADDING * 2, download_images=download_images)
            y += 24 + SHIPPED_ITEM_IMAGE_SIZE + ITEM_GAP

    _draw_copyright(draw, canvas, CARD_WIDTH//2-100, y)
    return canvas.crop((0, 0, CARD_WIDTH, y + 32))


def render_merchant_to_bytes(result: RocoMerchantResult, download_images: bool = True) -> bytes:
    image = render_merchant_card(result, download_images=download_images)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_info_panel(draw: ImageDraw.ImageDraw, canvas: Image.Image, result: RocoMerchantResult, y: int, download_images: bool) -> None:
    draw.rectangle((0, y, CARD_WIDTH, y + 76), fill=COLOR_PANEL)

    if download_images:
        with open(str(_ASSETS_DIR / "roco_images.txt"), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            [image1, image2]= [random.choice(lines).strip(), random.choice(lines).strip()]
        image1 = _load_item_image(image1, 72)
        image2 = _load_item_image(image2, 72)
    else:
        image1 = _placeholder_item_image(72, "精灵")
        image2 = _placeholder_item_image(72, "精灵")

    _draw_logo(canvas, image1, 50, 2, 72)
    _draw_logo(canvas, image2, CARD_WIDTH - 72 - 50, 2, 72)

    title = f"{result.short_date_text} 远行商人售卖商品" if result.short_date_text else "远行商人售卖商品"
    title_width = FONT_TITLE.getlength(title)
    draw.text((CARD_WIDTH // 2 - title_width // 2, y + 8), title, fill=COLOR_TEXT, font=FONT_TITLE)

    meta = result.time_range_text if result.live else result.next_refresh_text
    if result.duration_hours and result.live:
        meta = f"{meta} 时间段" if meta else f"持续 {result.duration_hours:g} 小时"
    if meta:
        meta_width = FONT_TIME.getlength(meta)
        draw.text((CARD_WIDTH // 2 - meta_width // 2, y + 44), meta, fill=COLOR_SUB, font=FONT_TIME)


def _draw_shipped_items(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    round: int,
    items: list[RocoMerchantItem],
    x: int,
    y: int,
    w: int,
    download_images: bool = True,
) -> None:
    box = (x, y, x + w, y + 24 + SHIPPED_ITEM_IMAGE_SIZE)
    draw.rounded_rectangle(box, radius=8, fill=COLOR_PANEL_ALT, outline=COLOR_LINE, width=1)

    text_x = x + PADDING
    text_y = y + (24 + SHIPPED_ITEM_IMAGE_SIZE - FONT_ITEM.size) // 2

    shipped_text = f"第 {round} 轮" if round != 0 else "全时段"
    length = int(FONT_ITEM.getlength("第 1 轮"))
    draw.text((text_x + (length - int(FONT_ITEM.getlength(shipped_text))) // 2, text_y), shipped_text, fill=COLOR_TITLE, font=FONT_ITEM)
    image_x = x + PADDING + length + PADDING
    image_y = y + 12
    for item in items:
        item_image = _load_item_image(item.icon_url, SHIPPED_ITEM_IMAGE_SIZE) if download_images else None
        if item_image is None:
            item_image = _placeholder_item_image(SHIPPED_ITEM_IMAGE_SIZE, "商品")
        canvas.paste(item_image, (image_x, image_y), item_image)
        image_x += SHIPPED_ITEM_IMAGE_SIZE + 12


def _draw_item(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: RocoMerchantItem,
    x: int,
    y: int,
    w: int,
    download_images: bool = True,
) -> None:

    box = (x, y, x + w, y + 120)
    panel_color = COLOR_VALUABLE if item.limit == 1 else COLOR_PANEL_ALT
    draw.rounded_rectangle(box, radius=8, fill=panel_color, outline=COLOR_LINE, width=1)

    image_x = x + 12
    image_y = y + 12
    item_image = _load_item_image(item.icon_url, ITEM_IMAGE_SIZE) if download_images else None
    if item_image is None:
        item_image = _placeholder_item_image(ITEM_IMAGE_SIZE, "商品")
    canvas.paste(item_image, (image_x, image_y), item_image)

    text_x = image_x + ITEM_IMAGE_SIZE + 12
    title_max_width = box[2] - PADDING - text_x

    title = _truncate_text(item.name or "未知商品", FONT_ITEM, title_max_width)
    draw.text((text_x, y + 20), title, fill=COLOR_TITLE, font=FONT_ITEM)

    # round_text = "全时段" if item.round == 0 else f"第 {item.round} 轮"
    # draw.text((text_x, y + 48), round_text, fill=COLOR_PRICE, font=FONT_BODY)
    limit_text = str(item.limit) if item.limit else "--"
    draw.text((text_x, y + 60), f"限购：{limit_text}", fill=COLOR_SUB, font=FONT_BODY)


def _draw_empty_state(draw: ImageDraw.ImageDraw, result: RocoMerchantResult, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, CARD_WIDTH - x, y + 120), radius=8, fill=COLOR_EMPTY_BG, outline=COLOR_LINE, width=1)
    draw.text((x + 24, y + 28), "远行商人进货去了~", fill=COLOR_TITLE, font=FONT_TITLE)
    next_text = result.next_refresh_text or "稍后再来看看"
    draw.text((x + 24, y + 68), next_text, fill=COLOR_SUB, font=FONT_BODY)


def _load_item_image(url: str, size: int) -> Image.Image | None:
    if not url:
        return None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.onebiji.com/"},
            timeout=8,
        )
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGBA")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        return _center_on_square(image, size)
    except Exception:
        return None


def _center_on_square(image: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    x = (size - image.width) // 2
    y = (size - image.height) // 2
    canvas.paste(image, (x, y), image)
    return canvas


def _placeholder_item_image(size: int, text: str) -> Image.Image:
    image = Image.new("RGBA", (size, size), (239, 244, 238, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=8, fill=(239, 244, 238), outline=COLOR_LINE)
    text_w = FONT_META.getlength(text)
    draw.text(((size - text_w) / 2, size / 2 - 13), text, fill=COLOR_MUTED, font=FONT_META)
    return image


def _draw_logo(image: Image.Image, logo_path: str | Image.Image, x: int, y: int, height: int) -> int:
    try:
        if isinstance(logo_path, Image.Image):
            logo = logo_path
        else:
            logo = Image.open(logo_path).convert("RGBA")
        w, h = logo.size
        scale = height / h
        new_w = int(w * scale)
        logo = logo.resize((new_w, height), Image.Resampling.LANCZOS)
        image.paste(logo, (x, y), logo)
        return new_w
    except Exception:
        return 0


def _draw_copyright(draw: ImageDraw.ImageDraw, canvas: Image.Image, x: int, y: int) -> None:
    text = "Made by"
    draw.text((x, y), text, fill=COLOR_MUTED, font=FONT_SMALL)
    text_w = FONT_SMALL.getlength(text)
    x += int(text_w) + 5
    logo_w = _draw_logo(canvas, str(_ASSETS_DIR / "logo.png"), x, y - 6, 32)
    text = "WoofZJ"
    x += logo_w + 5
    draw.text((x, y), text, fill=(255, 0, 0), font=FONT_SMALL)


def _truncate_text(text: str, font, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    for idx in range(len(text), 0, -1):
        candidate = text[:idx].rstrip() + "..."
        if font.getlength(candidate) <= max_width:
            return candidate
    return "..."
