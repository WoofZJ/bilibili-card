import io
import re
import requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageFilter
from douyin.models import DouyinWorkInfo, DouyinCommentsData, DouyinCommentItem

# ── 常量 ──────────────────────────────────────────
CARD_WIDTH = 736
CARD_HEIGHT_BASE = 730
COVER_HEIGHT = 450  # 800 / 16 * 9
PADDING = 16
LINE_GAP = 10
CARD_BG = (255, 255, 255)
AVATAR_SIZE = 60

COLOR_TITLE = (30, 30, 30)
COLOR_SUB = (102, 102, 102)
COLOR_ACCENT = (0x16, 0x18, 0x23)
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
    if size not in _font_config_cache:
        _font_config_cache[size] = FontConfig(size)
    return _font_config_cache[size]


_NOTDEF_REF: dict[tuple, bytes] = {}


def _is_tofu(char: str, font: ImageFont.FreeTypeFont) -> bool:
    """判断字符在指定字体中是否为 .notdef (豆腐块)"""
    key = (int(font.size), *font.getname())
    if key not in _NOTDEF_REF:
        _NOTDEF_REF[key] = bytes(font.getmask(chr(0xFFFE)))
    return bytes(font.getmask(char)) == _NOTDEF_REF[key]


# ── Emoji 正则（含 ZWJ、肤色、旗帜等完整序列）──
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

_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|(?:" + _EMOJI_BASE_CHARS +
    _EMOJI_MOD + "*"
    "(?:\u200D" + _EMOJI_BASE_CHARS +
    _EMOJI_MOD + "*)*)"
)

_SKIN_TONE_RE = re.compile('[\U0001F3FB-\U0001F3FF]')

EMOJI_TEXT_OFFSET = 6

# ── 段落类型常量 ──
SEG_TEXT = 'text'
SEG_EMOTE = 'emote'     # 抖音表情包（图片）
SEG_EMOJI = 'emoji'     # Unicode emoji（emoji 字体）
SEG_UNICODE = 'unicode'  # 主字体缺失的符号（回退字体）

Segment = tuple[str, str]

# ── 抖音表情包映射（名称 → 图片 URL）──
_DOUYIN_EMOTE_MAP: dict[str, str] = {
    "V5": "https://www.emojiall.com/images/60/douyin/clv.png",
    "给力": "https://www.emojiall.com/images/60/douyin/clw.png",
    "嘿哈": "https://www.emojiall.com/images/60/douyin/cm8.png",
    "加好友": "https://www.emojiall.com/images/60/douyin/cm9.png",
    "勾引": "https://www.emojiall.com/images/60/douyin/cmt.png",
    "机智": "https://www.emojiall.com/images/60/douyin/cn0.png",
    "来看我": "https://www.emojiall.com/images/60/douyin/cn1.png",
    "灵机一动": "https://www.emojiall.com/images/60/douyin/cn2.png",
    "困": "https://www.emojiall.com/images/60/douyin/cna.png",
    "疑问": "https://www.emojiall.com/images/60/douyin/cnb.png",
    "泣不成声": "https://www.emojiall.com/images/60/douyin/cnc.png",
    "小鼓掌": "https://www.emojiall.com/images/60/douyin/cnd.png",
    "发呆": "https://www.emojiall.com/images/60/douyin/cnf.png",
    "吐血": "https://www.emojiall.com/images/60/douyin/cnj.png",
    "酷拽": "https://www.emojiall.com/images/60/douyin/cnq.png",
    "泪奔": "https://www.emojiall.com/images/60/douyin/cnv.png",
    "抠鼻": "https://www.emojiall.com/images/60/douyin/co1.png",
    "互粉": "https://www.emojiall.com/images/60/douyin/co3.png",
    "去污粉": "https://www.emojiall.com/images/60/douyin/co8.png",
    "666": "https://www.emojiall.com/images/60/douyin/co9.png",
    "舔屏": "https://www.emojiall.com/images/60/douyin/cof.png",
    "鄙视": "https://www.emojiall.com/images/60/douyin/cog.png",
    "紫薇别走": "https://www.emojiall.com/images/60/douyin/coj.png",
    "不失礼貌的微笑": "https://www.emojiall.com/images/60/douyin/cop.png",
    "吐舌": "https://www.emojiall.com/images/60/douyin/coq.png",
    "呆无辜": "https://www.emojiall.com/images/60/douyin/cor.png",
    "白眼": "https://www.emojiall.com/images/60/douyin/cot.png",
    "吃瓜群众": "https://www.emojiall.com/images/60/douyin/cox.png",
    "绿帽子": "https://www.emojiall.com/images/60/douyin/coz.png",
    "皱眉": "https://www.emojiall.com/images/60/douyin/cp2.png",
    "擦汗": "https://www.emojiall.com/images/60/douyin/cp3.png",
    "强": "https://www.emojiall.com/images/60/douyin/cp7.png",
    "如花": "https://www.emojiall.com/images/60/douyin/cp8.png",
    "奋斗": "https://www.emojiall.com/images/60/douyin/cpc.png",
    "微笑": "https://www.emojiall.com/images/60/douyin/1f642.png",
    "害羞": "https://www.emojiall.com/images/60/douyin/1f60a.png",
    "击掌": "https://www.emojiall.com/images/60/douyin/1f64c.png",
    "左上": "https://www.emojiall.com/images/60/douyin/1f446.png",
    "握手": "https://www.emojiall.com/images/60/douyin/1f91d.png",
    "18禁": "https://www.emojiall.com/images/60/douyin/1f51e.png",
    "菜刀": "https://www.emojiall.com/images/60/douyin/1f52a.png",
    "爱心": "https://www.emojiall.com/images/60/douyin/2764.png",
    "心碎": "https://www.emojiall.com/images/60/douyin/1f494.png",
    "便便": "https://www.emojiall.com/images/60/douyin/1f4a9.png",
    "惊讶": "https://www.emojiall.com/images/60/douyin/1f632.png",
    "调皮": "https://www.emojiall.com/images/60/douyin/1f61b.png",
    "礼物": "https://www.emojiall.com/images/60/douyin/1f381.png",
    "蛋糕": "https://www.emojiall.com/images/60/douyin/1f382.png",
    "派对": "https://www.emojiall.com/images/60/douyin/1f389.png",
    "不看": "https://www.emojiall.com/images/60/douyin/1f648.png",
    "炸弹": "https://www.emojiall.com/images/60/douyin/1f4a3.png",
    "憨笑": "https://www.emojiall.com/images/60/douyin/1f600.png",
    "悠闲": "https://www.emojiall.com/images/60/douyin/1f6ac.png",
    "晕": "https://www.emojiall.com/images/60/douyin/1f635.png",
    "囧": "https://www.emojiall.com/images/60/douyin/1f644.png",
    "阴险": "https://www.emojiall.com/images/60/douyin/1f60f.png",
    "惊恐": "https://www.emojiall.com/images/60/douyin/1f628.png",
    "难过": "https://www.emojiall.com/images/60/douyin/1f641.png",
    "斜眼": "https://www.emojiall.com/images/60/douyin/1f612.png",
    "左哼哼": "https://www.emojiall.com/images/60/douyin/1f624.png",
    "右哼哼": "https://www.emojiall.com/images/60/douyin/1f624-new.png",
    "咒骂": "https://www.emojiall.com/images/60/douyin/1f92c.png",
    "咖啡": "https://www.emojiall.com/images/60/douyin/2615.png",
    "西瓜": "https://www.emojiall.com/images/60/douyin/1f349.png",
    "衰": "https://www.emojiall.com/images/60/douyin/1f622.png",
    "太阳": "https://www.emojiall.com/images/60/douyin/1f31e.png",
    "月亮": "https://www.emojiall.com/images/60/douyin/1f31c.png",
    "发": "https://www.emojiall.com/images/60/douyin/1f005.png",
    "猪头": "https://www.emojiall.com/images/60/douyin/1f437.png",
    "凋谢": "https://www.emojiall.com/images/60/douyin/1f940.png",
    "红包": "https://www.emojiall.com/images/60/douyin/1f9e7.png",
    "拳头": "https://www.emojiall.com/images/60/douyin/270a.png",
    "胜利": "https://www.emojiall.com/images/60/douyin/270c.png",
    "抱拳": "https://www.emojiall.com/images/60/douyin/1f64f.png",
    "闭嘴": "https://www.emojiall.com/images/60/douyin/1f910.png",
    "弱": "https://www.emojiall.com/images/60/douyin/1f44e.png",
    "左边": "https://www.emojiall.com/images/60/douyin/1f448.png",
    "右边": "https://www.emojiall.com/images/60/douyin/1f449.png",
    "送心": "https://www.emojiall.com/images/60/douyin/1f970.png",
    "耶": "https://www.emojiall.com/images/60/douyin/270c-new.png",
    "捂脸": "https://www.emojiall.com/images/60/douyin/1f926.png",
    "色": "https://www.emojiall.com/images/60/douyin/1f60d.png",
    "打脸": "https://www.emojiall.com/images/60/douyin/1f915.png",
    "大笑": "https://www.emojiall.com/images/60/douyin/1f604.png",
    "哈欠": "https://www.emojiall.com/images/60/douyin/1f971.png",
    "震惊": "https://www.emojiall.com/images/60/douyin/1f92f.png",
    "大金牙": "https://www.emojiall.com/images/60/douyin/1f9b7.png",
    "偷笑": "https://www.emojiall.com/images/60/douyin/1f92d.png",
    "石化": "https://www.emojiall.com/images/60/douyin/1f630.png",
    "思考": "https://www.emojiall.com/images/60/douyin/1f914.png",
    "可怜": "https://www.emojiall.com/images/60/douyin/1f97a.png",
    "嘘": "https://www.emojiall.com/images/60/douyin/1f92b.png",
    "撇嘴": "https://www.emojiall.com/images/60/douyin/1f615.png",
    "尴尬": "https://www.emojiall.com/images/60/douyin/1f605.png",
    "笑哭": "https://www.emojiall.com/images/60/douyin/1f602.png",
    "生病": "https://www.emojiall.com/images/60/douyin/1f637.png",
    "奸笑": "https://www.emojiall.com/images/60/douyin/1f60f-new.png",
    "得意": "https://www.emojiall.com/images/60/douyin/1f60e.png",
    "坏笑": "https://www.emojiall.com/images/60/douyin/1f62c.png",
    "抓狂": "https://www.emojiall.com/images/60/douyin/1f62b.png",
    "钱": "https://www.emojiall.com/images/60/douyin/1f911.png",
    "亲亲": "https://www.emojiall.com/images/60/douyin/1f61a.png",
    "恐惧": "https://www.emojiall.com/images/60/douyin/1f631.png",
    "愉快": "https://www.emojiall.com/images/60/douyin/1f604-new.png",
    "玫瑰": "https://www.emojiall.com/images/60/douyin/1f339.png",
    "快哭了": "https://www.emojiall.com/images/60/douyin/1f625.png",
    "翻白眼": "https://www.emojiall.com/images/60/douyin/1f644-new.png",
    "赞": "https://www.emojiall.com/images/60/douyin/1f44d.png",
    "鼓掌": "https://www.emojiall.com/images/60/douyin/1f44f.png",
    "感谢": "https://www.emojiall.com/images/60/douyin/1f64f-new.png",
    "嘴唇": "https://www.emojiall.com/images/60/douyin/1f444.png",
    "胡瓜": "https://www.emojiall.com/images/60/douyin/1f952.png",
    "流泪": "https://www.emojiall.com/images/60/douyin/1f622-new.png",
    "啤酒": "https://www.emojiall.com/images/60/douyin/1f37a.png",
    "我想静静": "https://www.emojiall.com/images/60/douyin/1f611.png",
    "委屈": "https://www.emojiall.com/images/60/douyin/1f641-new.png",
    "飞吻": "https://www.emojiall.com/images/60/douyin/1f618.png",
    "再见": "https://www.emojiall.com/images/60/douyin/1f44b.png",
    "听歌": "https://www.emojiall.com/images/60/douyin/1f3a7.png",
    "发怒": "https://www.emojiall.com/images/60/douyin/1f621.png",
    "绝望的凝视": "https://www.emojiall.com/images/60/douyin/1f61e.png",
    "看": "https://www.emojiall.com/images/60/douyin/1f436.png",
    "熊吉": "https://www.emojiall.com/images/60/douyin/1f43b.png",
    "骷髅": "https://www.emojiall.com/images/60/douyin/1f480.png",
    "黑脸": "https://www.emojiall.com/images/60/douyin/1f31a.png",
    "呲牙": "https://www.emojiall.com/images/60/douyin/1f601.png",
    "吐": "https://www.emojiall.com/images/60/douyin/1f92e.png",
    "流汗": "https://www.emojiall.com/images/60/douyin/1f613.png",
    "摸头": "https://www.emojiall.com/images/60/douyin/1f60c.png",
    "红脸": "https://www.emojiall.com/images/60/douyin/1f633.png",
    "尬笑": "https://www.emojiall.com/images/60/douyin/1f605-new.png",
    "做鬼脸": "https://www.emojiall.com/images/60/douyin/1f61c.png",
    "睡": "https://www.emojiall.com/images/60/douyin/1f62a.png",
    "惊喜": "https://www.emojiall.com/images/60/douyin/1f929.png",
    "敲打": "https://www.emojiall.com/images/60/douyin/1f915-new.png",
    "吐彩虹": "https://www.emojiall.com/images/60/douyin/1f308.png",
    "大哭": "https://www.emojiall.com/images/60/douyin/1f62d.png",
    "比心": "https://www.emojiall.com/images/60/douyin/1f91e.png",
    "强壮": "https://www.emojiall.com/images/60/douyin/1f4aa.png",
    "碰拳": "https://www.emojiall.com/images/60/douyin/1f91b.png",
    "OK": "https://www.emojiall.com/images/60/douyin/1f44c.png",
}

# 构建 [表情名] 正则（按名称长度降序匹配）
_EMOTE_KEYS_SORTED = sorted(_DOUYIN_EMOTE_MAP.keys(), key=len, reverse=True)
_EMOTE_RE = re.compile(r'\[(' + '|'.join(re.escape(k) for k in _EMOTE_KEYS_SORTED) + r')\]')

# ── 表情包加载与缓存 ─────────────────────────────────
_emote_cache: dict[str, Image.Image | None] = {}


def _load_emote(url: str, size: int) -> Image.Image | None:
    cache_key = f"{url}_{size}"
    if cache_key in _emote_cache:
        cached = _emote_cache[cache_key]
        return cached.copy() if cached else None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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


# ── 段落切分管线 ──────────────────────────────────

def _split_by_emotes(message: str) -> list[Segment]:
    """按抖音 [表情名] 切分消息"""
    segments: list[Segment] = []
    last_end = 0
    for match in _EMOTE_RE.finditer(message):
        if match.start() > last_end:
            segments.append((SEG_TEXT, message[last_end:match.start()]))
        emote_name = match.group(1)
        segments.append((SEG_EMOTE, _DOUYIN_EMOTE_MAP[emote_name]))
        last_end = match.end()
    if last_end < len(message):
        segments.append((SEG_TEXT, message[last_end:]))
    return segments if segments else [(SEG_TEXT, message)]


def _split_by_emoji(segments: list[Segment]) -> list[Segment]:
    """在 text 段落中识别 emoji 序列"""
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


def _parse_message_segments(message: str, font_config: FontConfig | None = None) -> list[Segment]:
    """将评论消息解析为 text / emote / emoji / unicode 段落列表"""
    segments = _split_by_emotes(message)
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

    def _flush_line():
        nonlocal current_line, current_width
        lines.append(current_line)
        current_line = []
        current_width = 0.0

    def _remaining_chars_count(idx, text_discount=0):
        count = -text_discount
        for seg_type, seg_data in segments[idx:]:
            if seg_type == SEG_EMOTE or seg_type == SEG_EMOJI:
                count += 1
            else:
                count += len(seg_data)
        return count

    for idx, (seg_type, seg_data) in enumerate(segments):
        if seg_type == SEG_EMOTE:
            w = emote_size + 2
            if current_width + w > max_width and current_line:
                _flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaining_chars_count(idx)
            current_line.append((SEG_EMOTE, seg_data))
            current_width += w
        elif seg_type == SEG_EMOJI:
            w = font_config.emoji.getlength(seg_data)
            if current_width + w > max_width and current_line:
                _flush_line()
                if len(lines) >= max_lines:
                    return lines, _remaining_chars_count(idx)
            current_line.append((SEG_EMOJI, seg_data))
            current_width += w
        else:  # SEG_TEXT, SEG_UNICODE
            font = font_config.fallback if seg_type == SEG_UNICODE else font_config.main
            for i, ch in enumerate(seg_data):
                if ch == '\n':
                    _flush_line()
                    if len(lines) >= max_lines:
                        return lines, _remaining_chars_count(idx, len(seg_data) - i)
                    continue
                ch_w = font.getlength(ch)
                if current_width + ch_w > max_width and current_line:
                    _flush_line()
                    if len(lines) >= max_lines:
                        return lines, _remaining_chars_count(idx, len(seg_data) - i)
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
            if seg_type == SEG_TEXT:
                text_y = y + (line_height - font_config.main.size) // 2
                draw.text((cx, text_y), seg_data, fill=text_color, font=font_config.main)
                cx += int(font_config.main.getlength(seg_data))
            elif seg_type == SEG_EMOJI:
                emoji_y = y + (line_height - font_config.emoji.size) // 2 + EMOJI_TEXT_OFFSET
                draw.text((cx, emoji_y), seg_data, fill=text_color, font=font_config.emoji, embedded_color=True)
                cx += int(font_config.emoji.getlength(seg_data))
            elif seg_type == SEG_UNICODE:
                unicode_y = y + (line_height - font_config.fallback.size) // 2
                draw.text((cx, unicode_y), seg_data, fill=text_color, font=font_config.fallback)
                cx += int(font_config.fallback.getlength(seg_data))
            elif seg_type == SEG_EMOTE:
                emote_img = _load_emote(seg_data, emote_size)
                if emote_img:
                    emote_y = y + (line_height - emote_size) // 2
                    canvas.paste(emote_img, (int(cx), int(emote_y)), emote_img)
                    cx += emote_size + 1
                else:
                    # 加载失败时显示原始文本
                    text_y = y + (line_height - font_config.main.size) // 2
                    draw.text((cx, text_y), "[?]", fill=text_color, font=font_config.main)
                    cx += int(font_config.main.getlength("[?]"))
        y += line_height
        total_h += line_height
    return total_h


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
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_text_with_fallback(draw: ImageDraw.ImageDraw, xy, text: str, fill, font, canvas=None):
    """绘制文本，自动使用 emoji 字体和回退字体"""
    fc = _get_font_config(int(font.size))
    x, y = xy
    cx = 0.0

    last_end = 0
    for match in _EMOJI_RE.finditer(text):
        if match.start() > last_end:
            seg = text[last_end:match.start()]
            draw.text((x + cx, y), seg, fill=fill, font=fc.main)
            cx += fc.main.getlength(seg)
        emoji_text = match.group()
        draw.text((x + cx, y + EMOJI_TEXT_OFFSET), emoji_text, fill=fill, font=fc.emoji, embedded_color=True)
        cx += fc.emoji.getlength(emoji_text)
        last_end = match.end()

    if last_end < len(text):
        seg = text[last_end:]
        draw.text((x + cx, y), seg, fill=fill, font=fc.main)
        cx += fc.main.getlength(seg)

    return cx


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

def _load_cover(cover_url: str, first_frame_url: str = "") -> Image.Image:
    """加载 16:9 封面：前景封面居中且高度撑满，背景为首帧模糊画面。"""
    try:
        # 优先使用首帧作为背景，无首帧时回退到封面
        bg_url = first_frame_url or cover_url
        bg_resp = requests.get(bg_url, timeout=10)
        bg_resp.raise_for_status()
        bg_img = Image.open(io.BytesIO(bg_resp.content)).convert("RGBA")

        # 背景填满 16:9，采用 center-crop 再高斯模糊
        target_ratio = CARD_WIDTH / COVER_HEIGHT
        bw, bh = bg_img.size
        bg_ratio = bw / bh if bh else target_ratio
        if bg_ratio > target_ratio:
            new_w = int(bh * target_ratio)
            left = (bw - new_w) // 2
            bg_img = bg_img.crop((left, 0, left + new_w, bh))
        elif bg_ratio < target_ratio:
            new_h = int(bw / target_ratio)
            top = (bh - new_h) // 2
            bg_img = bg_img.crop((0, top, bw, top + new_h))
        bg_img = bg_img.resize((CARD_WIDTH, COVER_HEIGHT), Image.Resampling.LANCZOS)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=16))

        # 叠加一层浅暗遮罩，提升前景封面可读性
        overlay = Image.new("RGBA", (CARD_WIDTH, COVER_HEIGHT), (0, 0, 0, 35))
        bg_img.alpha_composite(overlay)

        # 前景封面：高度撑满，宽度按比例缩放并水平居中
        fg_resp = requests.get(cover_url, timeout=10)
        fg_resp.raise_for_status()
        fg_img = Image.open(io.BytesIO(fg_resp.content)).convert("RGBA")
        fw, fh = fg_img.size
        if fh <= 0:
            return bg_img

        scale = COVER_HEIGHT / fh
        new_w = max(1, int(fw * scale))
        fg_img = fg_img.resize((new_w, COVER_HEIGHT), Image.Resampling.LANCZOS)

        if new_w > CARD_WIDTH:
            left = (new_w - CARD_WIDTH) // 2
            fg_img = fg_img.crop((left, 0, left + CARD_WIDTH, COVER_HEIGHT))
            x = 0
        else:
            x = (CARD_WIDTH - new_w) // 2

        bg_img.paste(fg_img, (x, 0), fg_img)
        return bg_img
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

    title_lines = _wrap_text(work.title, FONT_TITLE, content_width, max_lines=5)
    title_line_height = 48
    title_height = len(title_lines) * title_line_height
    total_height = CARD_HEIGHT_BASE + title_height

    canvas = Image.new("RGBA", (CARD_WIDTH, total_height), (0, 0, 0, 0))

    # 背景
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, CARD_WIDTH, total_height), fill=(255, 255, 255))

    # 封面
    if download_cover and work.cover:
        cover = _load_cover(work.cover, work.first_frame)
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

    _draw_logo(canvas, str(_ASSETS_DIR / "douyin.png"), 650, y_cursor+5, AVATAR_SIZE-10)
    y_cursor += AVATAR_SIZE + LINE_GAP

    # 发布时间、分辨率
    meta_parts = []
    if work.create_time:
        meta_parts.append(f"发布于 {work.create_time_str}")
    if work.width and work.height:
        meta_parts.append(f"分辨率：{work.resolution_str}")
    if work.video_size > 0:
        meta_parts.append(f"{work.video_size / 1024 / 1024:.2f} MB")
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
        ("推荐", DouyinWorkInfo.format_count(work.recommend_count)),
        ("弹幕", DouyinWorkInfo.format_count(work.danmaku_count)),
        ("评论", DouyinWorkInfo.format_count(work.comment_count)),
        ("收藏", DouyinWorkInfo.format_count(work.collect_count)),
        ("分享", DouyinWorkInfo.format_count(work.share_count)),
    ]
    item_width = content_width // len(stats)
    x = PADDING
    for label, value in stats:
        _draw_stat_item(draw, x, y_cursor, item_width, label, value)
        x += item_width
    y_cursor += FONT_STAT_LABEL.size + FONT_STAT_VALUE.size + LINE_GAP + 4

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
COMMENT_CARD_WIDTH = 760
COMMENT_PADDING = 20
COMMENT_AVATAR_SIZE = 48
COMMENT_SUB_AVATAR_SIZE = 36
COLOR_COMMENT_BG = (255, 255, 255)
COLOR_COMMENT_HEADER_TEXT = (0x16, 0x18, 0x23)
COLOR_COMMENT_HEADER_BG = (0xc4, 0xb7, 0xd7)
COLOR_AUTHOR_LIKED_BG = (254, 44, 85)
COLOR_AUTHOR_LIKED_TEXT = (255, 255, 255)
COLOR_LIKE_TEXT = (255, 0, 80)
COLOR_TIME_TEXT = (153, 153, 153)
COLOR_REPLY_COUNT = (109, 192, 233)
COLOR_USERNAME = (51, 51, 51)
COLOR_MESSAGE = (34, 34, 34)
COLOR_SUB_LINE = (229, 233, 239)
COLOR_IP_TEXT = (80, 0, 160)

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

    # 使用段落系统计算消息行数
    msg_line_h = 30 if is_sub else 32
    emote_size = 26 if is_sub else 30
    fc = _get_font_config(int(font_msg.size))
    segments = _parse_message_segments(comment.text, fc)
    wrapped, _ = _wrap_message_segments(segments, fc, text_width, max_lines=6, emote_size=emote_size)
    msg_h = len(wrapped) * msg_line_h

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

    # 用户名行: [作者赞] 用户名
    name_y = y + 2
    badge_x = text_x

    if comment.is_author_digged:
        w = _draw_small_badge(draw, badge_x, name_y, "作者赞过", COLOR_AUTHOR_LIKED_BG, COLOR_AUTHOR_LIKED_TEXT)
        badge_x += w + 6

    _draw_text_with_fallback(draw, (badge_x, name_y), comment.nickname, fill=COLOR_USERNAME, font=font_username, canvas=canvas)

    name_line_h = 28 if is_sub else 30
    y += name_line_h + 6

    # 评论内容（使用段落系统）
    msg_line_h = 30 if is_sub else 32
    emote_size = 26 if is_sub else 30
    fc = _get_font_config(int(font_msg.size))
    segments = _parse_message_segments(comment.text, fc)
    wrapped, _ = _wrap_message_segments(segments, fc, text_width, max_lines=6, emote_size=emote_size)
    msg_h = _draw_message_with_emotes(canvas, draw, wrapped, text_x, y, fc, msg_line_h, emote_size)
    y += msg_h

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
    meta_x += int(font_meta.getlength(like_text)) + PADDING

    if comment.ip_label:
        ip_text = f"{comment.ip_label}"
        draw.text((meta_x, y), ip_text, fill=COLOR_IP_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(ip_text)) + PADDING

    time_text = comment.create_time_str
    if time_text:
        draw.text((meta_x, y), time_text, fill=COLOR_TIME_TEXT, font=font_meta)
        meta_x += int(font_meta.getlength(time_text)) + PADDING

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
    header_text = f"评论 ({comments_data.total})"
    header_tw = FONT_COMMENT_HEADER.getlength(header_text)
    height = FONT_COMMENT_HEADER.getbbox(header_text)[3]
    logo_w = _draw_logo(canvas, str(_ASSETS_DIR / "douyin.png"), COMMENT_PADDING*2, (header_h-40) // 2, 40)
    _draw_logo(canvas, str(_ASSETS_DIR / "douyin.png"), COMMENT_CARD_WIDTH - COMMENT_PADDING*2 - logo_w, (header_h-40) // 2, 40)
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
