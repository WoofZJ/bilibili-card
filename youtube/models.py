from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import re


# ── 语言代码 → 中文名映射 ────────────────────────────
_LANGUAGE_MAP: dict[str, str] = {
    "aa": "阿法尔语", "ab": "阿布哈兹语", "af": "南非荷兰语", "am": "阿姆哈拉语",
    "ar": "阿拉伯语", "as": "阿萨姆语", "az": "阿塞拜疆语", "be": "白俄罗斯语",
    "bg": "保加利亚语", "bn": "孟加拉语", "bo": "藏语", "bs": "波斯尼亚语",
    "ca": "加泰罗尼亚语", "cs": "捷克语", "cy": "威尔士语", "da": "丹麦语",
    "de": "德语", "el": "希腊语", "en": "英语", "en-US": "英语(美国)",
    "en-GB": "英语(英国)", "eo": "世界语", "es": "西班牙语", "et": "爱沙尼亚语",
    "eu": "巴斯克语", "fa": "波斯语", "fi": "芬兰语", "fil": "菲律宾语",
    "fr": "法语", "ga": "爱尔兰语", "gl": "加利西亚语", "gu": "古吉拉特语",
    "ha": "豪萨语", "he": "希伯来语", "hi": "印地语", "hr": "克罗地亚语",
    "hu": "匈牙利语", "hy": "亚美尼亚语", "id": "印尼语", "is": "冰岛语",
    "it": "意大利语", "ja": "日语", "jv": "爪哇语", "ka": "格鲁吉亚语",
    "kk": "哈萨克语", "km": "高棉语", "kn": "卡纳达语", "ko": "韩语",
    "ku": "库尔德语", "ky": "吉尔吉斯语", "la": "拉丁语", "lo": "老挝语",
    "lt": "立陶宛语", "lv": "拉脱维亚语", "mg": "马达加斯加语", "mi": "毛利语",
    "mk": "马其顿语", "ml": "马拉雅拉姆语", "mn": "蒙古语", "mr": "马拉地语",
    "ms": "马来语", "mt": "马耳他语", "my": "缅甸语", "nb": "挪威博克马尔语",
    "ne": "尼泊尔语", "nl": "荷兰语", "nn": "挪威尼诺斯克语", "no": "挪威语",
    "pa": "旁遮普语", "pl": "波兰语", "ps": "普什图语", "pt": "葡萄牙语",
    "pt-BR": "葡萄牙语(巴西)", "ro": "罗马尼亚语", "ru": "俄语",
    "sd": "信德语", "si": "僧伽罗语", "sk": "斯洛伐克语", "sl": "斯洛文尼亚语",
    "so": "索马里语", "sq": "阿尔巴尼亚语", "sr": "塞尔维亚语", "su": "巽他语",
    "sv": "瑞典语", "sw": "斯瓦希里语", "ta": "泰米尔语", "te": "泰卢固语",
    "tg": "塔吉克语", "th": "泰语", "tk": "土库曼语", "tl": "他加禄语",
    "tr": "土耳其语", "uk": "乌克兰语", "ur": "乌尔都语", "uz": "乌兹别克语",
    "vi": "越南语", "yo": "约鲁巴语",
    "zh": "中文", "zh-CN": "简体中文", "zh-TW": "繁体中文", "zh-Hant": "繁体中文",
    "zh-Hans": "简体中文", "zh-HK": "中文(香港)",
    "zu": "祖鲁语",
}


def language_name(code: str) -> str:
    """将语言代码转换为中文名称，未知代码原样返回"""
    if not code:
        return ""
    if code in _LANGUAGE_MAP:
        return _LANGUAGE_MAP[code]
    # 尝试匹配基础语言代码（如 "en-AU" -> "en"）
    base = code.split("-")[0].split("_")[0]
    if base in _LANGUAGE_MAP:
        return _LANGUAGE_MAP[base]
    return code


class YouTubeVideoInfo(BaseModel):
    """YouTube 视频信息模型"""
    video_id: str
    title: str
    description: str = ""
    channel_id: str = ""
    channel_title: str = ""
    channel_avatar: str = ""  # 频道头像URL
    published_at: str = ""  # ISO 8601 时间字符串
    thumbnail: str = ""  # 缩略图URL（最高分辨率）

    # 内容详情
    duration: int = 0  # 秒
    dimension: str = ""  # 2d / 3d
    definition: str = ""  # hd / sd
    caption: bool = False

    # 数据统计
    view_count: int = 0
    like_count: int = 0
    favorite_count: int = 0
    comment_count: int = 0
    localization_count: int = 0  # 本地化版本数量

    # 语言
    default_language: str = ""
    default_audio_language: str = ""

    @property
    def duration_str(self) -> str:
        """格式化时长 -> MM:SS 或 HH:MM:SS"""
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def published_at_str(self) -> str:
        """格式化发布时间"""
        if self.published_at:
            try:
                dt = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return self.published_at
        return ""

    @staticmethod
    def format_count(n: int) -> str:
        """格式化数字"""
        if n >= 100000000:
            return f"{n / 100000000:.1f}亿"
        if n >= 10000:
            return f"{n / 10000:.1f}万"
        return str(n)

    @staticmethod
    def _parse_iso8601_duration(duration_str: str) -> int:
        """解析 ISO 8601 时长格式 (如 PT4M3S) 为秒数"""
        match = re.match(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
            duration_str,
        )
        if not match:
            return 0
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    @classmethod
    def from_api(cls, data: dict) -> "YouTubeVideoInfo":
        """从 YouTube Data API v3 返回的 videos.list 数据构造"""
        items = data.get("items", [])
        if not items:
            raise ValueError("API 返回数据中无 items")

        item = items[0]
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        statistics = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})

        # 选择最高分辨率缩略图
        thumbnail_url = ""
        for key in ("maxres", "standard", "high", "medium", "default"):
            if key in thumbnails:
                thumbnail_url = thumbnails[key].get("url", "")
                break

        # 解析时长
        duration_seconds = cls._parse_iso8601_duration(
            content_details.get("duration", "")
        )

        # 本地化版本数量
        localizations = item.get("localizations", {})
        localization_count = len(localizations) if localizations else 0

        return cls(
            video_id=item.get("id", ""),
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt", ""),
            thumbnail=thumbnail_url,
            duration=duration_seconds,
            dimension=content_details.get("dimension", ""),
            definition=content_details.get("definition", ""),
            caption=content_details.get("caption", "false") == "true",
            view_count=int(statistics.get("viewCount", 0)),
            like_count=int(statistics.get("likeCount", 0)),
            favorite_count=int(statistics.get("favoriteCount", 0)),
            comment_count=int(statistics.get("commentCount", 0)),
            localization_count=localization_count,
            default_language=snippet.get("defaultLanguage", ""),
            default_audio_language=snippet.get("defaultAudioLanguage", ""),
        )

    @staticmethod
    def extract_channel_avatar(channel_data: dict) -> str:
        """从 channels.list API 返回数据中提取频道头像 URL (medium)"""
        items = channel_data.get("items", [])
        if not items:
            return ""
        snippet = items[0].get("snippet", {})
        thumbnails = snippet.get("thumbnails", {})
        medium = thumbnails.get("medium", {})
        return medium.get("url", "")


class YouTubeCommentItem(BaseModel):
    """YouTube 单条评论"""
    comment_id: str  # 评论ID
    video_id: str = ""  # 视频ID
    author_name: str  # 用户名
    author_avatar: str = ""  # 头像URL
    author_channel_url: str = ""  # 作者频道URL
    author_channel_id: str = ""  # 作者频道ID
    text: str  # 评论内容（原始文本）
    text_display: str = ""  # 评论内容（HTML格式）
    like_count: int = 0  # 点赞数
    published_at: str = ""  # 发布时间 ISO 8601
    updated_at: str = ""  # 更新时间 ISO 8601
    reply_count: int = 0  # 回复数量
    is_channel_owner: bool = False  # 是否为频道主
    sub_comments: list["YouTubeCommentItem"] = []  # 子评论

    @property
    def published_at_str(self) -> str:
        if self.published_at:
            try:
                dt = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return self.published_at
        return ""

    @classmethod
    def from_comment_snippet(cls, snippet: dict, channel_owner_id: str = "") -> "YouTubeCommentItem":
        """从单条 comment 的 snippet 构造"""
        author_channel_id = snippet.get("authorChannelId", {}).get("value", "")
        return cls(
            comment_id=snippet.get("id", "") or snippet.get("commentId", ""),
            video_id=snippet.get("videoId", ""),
            author_name=snippet.get("authorDisplayName", "").removeprefix("@"),
            author_avatar=snippet.get("authorProfileImageUrl", ""),
            author_channel_url=snippet.get("authorChannelUrl", ""),
            author_channel_id=author_channel_id,
            text=snippet.get("textOriginal", ""),
            text_display=snippet.get("textDisplay", ""),
            like_count=snippet.get("likeCount", 0),
            published_at=snippet.get("publishedAt", ""),
            updated_at=snippet.get("updatedAt", ""),
            is_channel_owner=(author_channel_id == channel_owner_id and bool(channel_owner_id)),
        )

    @classmethod
    def from_top_level_comment(cls, comment: dict, channel_owner_id: str = "", reply_count: int = 0) -> "YouTubeCommentItem":
        """从 topLevelComment 对象构造"""
        snippet = comment.get("snippet", {})
        item = cls.from_comment_snippet(snippet, channel_owner_id)
        item.comment_id = comment.get("id", item.comment_id)
        item.reply_count = reply_count
        return item


class YouTubeCommentsData(BaseModel):
    """YouTube 评论数据"""
    total: int = 0  # 总评论数
    comments: list[YouTubeCommentItem] = []  # 评论列表

    @classmethod
    def from_api(cls, data: dict) -> "YouTubeCommentsData":
        """从 commentThreads.list API 返回数据构造"""
        page_info = data.get("pageInfo", {})
        total = page_info.get("totalResults", 0)
        items = data.get("items", [])

        comments = []
        for thread in items:
            thread_snippet = thread.get("snippet", {})
            channel_owner_id = thread_snippet.get("channelId", "")
            reply_count = thread_snippet.get("totalReplyCount", 0)

            # 顶级评论
            top_comment_data = thread_snippet.get("topLevelComment", {})
            top_comment = YouTubeCommentItem.from_top_level_comment(
                top_comment_data, channel_owner_id, reply_count
            )

            # 回复
            replies_data = thread.get("replies", {})
            reply_comments = replies_data.get("comments", [])
            for reply in reply_comments:
                sub = YouTubeCommentItem.from_comment_snippet(
                    reply.get("snippet", {}), channel_owner_id
                )
                sub.comment_id = reply.get("id", sub.comment_id)
                top_comment.sub_comments.append(sub)

            comments.append(top_comment)

        return cls(total=total, comments=comments)
