from html import unescape
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EmoteInfo(BaseModel):
    """表情包信息"""
    text: str  # 表情文本，如 "[doge]"
    url: str = ""  # 表情图片URL
    size: int = 1  # 1=小表情(行内), 2=大表情


class JumpUrlInfo(BaseModel):
    """jump_url 信息（链接/搜索词的展示信息）"""
    title: str = ""  # 显示标题
    prefix_icon: str = ""  # 前缀图标 URL


class PictureInfo(BaseModel):
    """评论配图信息"""
    img_src: str  # 图片URL
    img_width: int = 0  # 原始宽度
    img_height: int = 0  # 原始高度
    img_size: float = 0  # 文件大小(KB)


class CommentItem(BaseModel):
    """单条评论"""
    rpid: int  # 评论ID
    uname: str  # 用户名
    avatar: str  # 头像URL
    level: int = 0  # 用户等级
    message: str  # 评论内容
    like: int = 0  # 点赞数
    ctime: int = 0  # 发布时间戳
    time_desc: str = ""  # 时间描述，如 "6天前发布"
    is_up: bool = False  # 是否UP主
    is_top: bool = False  # 是否置顶
    is_vip: bool = False  # 是否大会员
    vip_label: str = ""  # 大会员标签文字
    is_contractor: bool = False  # 是否原始粉丝
    contract_desc: str = ""  # 粉丝描述
    rcount: int = 0  # 回复数量
    emotes: dict[str, EmoteInfo] = {}  # 表情包映射 {"[doge]": EmoteInfo}
    at_names: dict[str, int] = {}  # @提及映射 {"用户名": mid}
    jump_urls: dict[str, JumpUrlInfo] = {}  # jump_url 映射 {"文本/URL": JumpUrlInfo}
    pictures: list[PictureInfo] = []  # 评论配图列表
    sub_replies: list["CommentItem"] = []  # 子评论

    @classmethod
    def from_reply(cls, reply: dict, up_mid: int = 0, is_top: bool = False) -> "CommentItem":
        """从 API 返回的单条 reply 构造"""
        member = reply.get("member", {})
        content = reply.get("content", {})
        reply_control = reply.get("reply_control", {})
        level_info = member.get("level_info", {})
        vip = member.get("vip", {})

        sub_replies = []
        if reply.get("replies"):
            for sub in reply["replies"]:
                sub_replies.append(cls.from_reply(sub, up_mid=up_mid))

        mid = int(member.get("mid", 0))

        # 解析表情包
        emotes = {}
        emote_data = content.get("emote", {})
        if emote_data:
            for key, val in emote_data.items():
                emotes[key] = EmoteInfo(
                    text=val.get("text", key),
                    url=val.get("url", ""),
                    size=val.get("meta", {}).get("size", 1),
                )

        # 解析 @提及
        at_names = {}
        at_name_data = content.get("at_name_to_mid", {}) or {}
        for name, mid_val in at_name_data.items():
            at_names[name] = int(mid_val) if isinstance(mid_val, str) else mid_val

        # 解析 jump_url
        jump_urls = {}
        jump_url_data = content.get("jump_url", {}) or {}
        for key, val in jump_url_data.items():
            title = val.get("title", "")
            if title:
                jump_urls[key] = JumpUrlInfo(
                    title=title,
                    prefix_icon=val.get("prefix_icon", ""),
                )

        # 解析评论配图
        pictures = []
        pic_data = content.get("pictures", []) or []
        for pic in pic_data:
            pictures.append(PictureInfo(
                img_src=pic.get("img_src", ""),
                img_width=pic.get("img_width", 0),
                img_height=pic.get("img_height", 0),
                img_size=pic.get("img_size", 0.0),
            ))

        return cls(
            rpid=reply.get("rpid", 0),
            uname=member.get("uname", ""),
            avatar=member.get("avatar", ""),
            level=level_info.get("current_level", 0),
            message=content.get("message", ""),
            like=reply.get("like", 0),
            ctime=reply.get("ctime", 0),
            time_desc=reply_control.get("time_desc", ""),
            is_up=(mid == up_mid),
            is_top=is_top,
            is_vip=(vip.get("vipStatus", 0) == 1),
            vip_label=vip.get("label", {}).get("text", ""),
            is_contractor=member.get("is_contractor", False),
            contract_desc=member.get("contract_desc", ""),
            rcount=reply.get("rcount", 0),
            emotes=emotes,
            at_names=at_names,
            jump_urls=jump_urls,
            pictures=pictures,
            sub_replies=sub_replies,
        )


class CommentsData(BaseModel):
    """评论数据"""
    total: int = 0  # 总评论数
    comments: list[CommentItem] = []  # 评论列表
    top_comment: Optional[CommentItem] = None  # 置顶评论

    @classmethod
    def from_api(cls, data: dict) -> "CommentsData":
        """从 API 返回的评论数据构造"""
        cursor = data.get("cursor", {})
        total = cursor.get("all_count", 0)
        up_mid = data.get("upper", {}).get("mid", 0)

        # 置顶评论
        top_comment = None
        top = data.get("top", {})
        if top:
            upper_top = top.get("upper")
            if upper_top:
                top_comment = CommentItem.from_reply(upper_top, up_mid=up_mid, is_top=True)

        # 普通评论
        comments = []
        replies = data.get("replies", []) or []
        for reply in replies:
            # 跳过已经作为置顶的评论
            if top_comment and reply.get("rpid") == top_comment.rpid:
                continue
            comments.append(CommentItem.from_reply(reply, up_mid=up_mid))

        return cls(
            total=total,
            comments=comments,
            top_comment=top_comment,
        )

class Staff(BaseModel):
    """UP主信息"""
    mid: int
    title: str
    name: str
    face: str

class VideoInfo(BaseModel):
    """B站视频信息模型"""
    bvid: str
    title: str
    cover: str  # 封面图URL
    description: str
    publish_time: int  # Unix时间戳
    duration: int  # 秒

    # UP主信息
    author_name: str
    author_mid: int
    author_face: str  # 头像URL

    # 数据统计
    view: int = 0
    danmaku: int = 0
    reply: int = 0
    favorite: int = 0
    coin: int = 0
    share: int = 0
    like: int = 0
    dislike: int = 0

    # 分辨率
    width: int = 0
    height: int = 0

    # 人员列表
    staffs: list[Staff] = []

    @property
    def duration_str(self) -> str:
        """格式化时长 -> MM:SS 或 HH:MM:SS"""
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def publish_time_str(self) -> str:
        """格式化发布时间"""
        return datetime.fromtimestamp(self.publish_time).strftime("%Y-%m-%d %H:%M")

    @property
    def resolution_str(self) -> str:
        """分辨率标签"""
        return f"{self.width}x{self.height}"

    @staticmethod
    def format_count(n: int) -> str:
        """格式化数字"""
        if n >= 1000000:
            return f"{n / 10000:.0f}万"
        if n >= 10000:
            return f"{n / 10000:.1f}万"
        return str(n)

    @classmethod
    def from_api(cls, info: dict) -> "VideoInfo":
        """从bilibili API返回的video.get_info()数据构造"""
        stat = info.get("stat", {})
        owner = info.get("owner", {})
        dim = info.get("dimension", {})
        desc: str = info.get("desc", "")
        desc = desc.strip("\r\n\t -")
        return cls(
            bvid=info["bvid"],
            title=info["title"],
            cover=info.get("pic", ""),
            description=desc,
            publish_time=info.get("pubdate", 0),
            duration=info.get("duration", 0),
            author_name=owner.get("name", ""),
            author_mid=owner.get("mid", 0),
            author_face=owner.get("face", ""),
            view=stat.get("view", 0),
            danmaku=stat.get("danmaku", 0),
            reply=stat.get("reply", 0),
            favorite=stat.get("favorite", 0),
            coin=stat.get("coin", 0),
            share=stat.get("share", 0),
            like=stat.get("like", 0),
            dislike=stat.get("dislike", 0),
            width=dim.get("width", 0),
            height=dim.get("height", 0),
            staffs=[Staff(**s) for s in info.get("staff", [])]
        )


class LiveRoomInfo(BaseModel):
    """B站直播间信息模型"""
    uid: int = 0
    room_id: int = 0
    short_id: int = 0
    title: str = ""
    cover: str = ""
    keyframe: str = ""
    description: str = ""
    live_status: int = 0
    live_start_time: int = 0
    area_name: str = ""
    parent_area_name: str = ""
    guard_count: int = 0

    # 主播信息
    anchor_name: str = ""
    anchor_face: str = ""

    # 数据统计
    popularity: int = 0
    popularity_text: str = ""
    watched: int = 0
    likes: int = 0
    attention: int = 0
    anchor_level: int = 0
    medal_name: str = ""
    fansclub: int = 0

    @property
    def display_room_id(self) -> int:
        """优先展示短号，没有短号时展示真实房间号"""
        return self.short_id or self.room_id

    @property
    def live_status_str(self) -> str:
        """直播状态标签"""
        if self.live_status == 1:
            return "直播中"
        if self.live_status == 2:
            return "轮播中"
        return "未开播"

    @property
    def live_start_time_str(self) -> str:
        """格式化开播时间"""
        if self.live_start_time <= 0:
            return "未开播"
        return datetime.fromtimestamp(self.live_start_time).strftime("%Y-%m-%d %H:%M")

    @property
    def area_str(self) -> str:
        """分区标签"""
        if self.parent_area_name and self.area_name:
            return f"{self.parent_area_name}/{self.area_name}"
        return self.area_name or self.parent_area_name

    @property
    def preview_image(self) -> str:
        """优先使用直播关键帧作为卡片大图"""
        return self.keyframe or self.cover

    @staticmethod
    def format_count(n: int) -> str:
        """格式化数字"""
        return VideoInfo.format_count(n)

    @classmethod
    def from_api(cls, info: dict) -> "LiveRoomInfo":
        """从 bilibili_api live.LiveRoom.get_room_info() 数据构造"""
        if "data" in info and isinstance(info["data"], dict) and "room_info" not in info:
            info = info["data"]

        room = info.get("room_info", {}) or {}
        anchor = info.get("anchor_info", {}) or {}
        base = anchor.get("base_info", {}) or {}
        live_info = anchor.get("live_info", {}) or {}
        relation = anchor.get("relation_info", {}) or {}
        medal = anchor.get("medal_info", {}) or {}
        watched = info.get("watched_show", {}) or {}
        like_info = info.get("like_info_v3", {}) or {}
        popularity = info.get("popularity", {}) or {}
        news = info.get("news_info", {}) or {}
        guard_info = info.get("guard_info", {}) or {}

        def _to_int(value, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        popularity_value = popularity.get("popularity", room.get("online", 0))
        description = room.get("description") or news.get("content") or ""

        return cls(
            uid=_to_int(room.get("uid", 0)),
            room_id=_to_int(room.get("room_id", 0)),
            short_id=_to_int(room.get("short_id", 0)),
            title=room.get("title") or "",
            cover=room.get("cover") or "",
            keyframe=room.get("keyframe") or "",
            description=str(description).strip(),
            live_status=_to_int(room.get("live_status", 0)),
            live_start_time=_to_int(room.get("live_start_time", 0)),
            area_name=room.get("area_name") or "",
            parent_area_name=room.get("parent_area_name") or "",
            anchor_name=base.get("uname") or "",
            anchor_face=base.get("face") or "",
            popularity=_to_int(popularity_value),
            popularity_text=popularity.get("popularity_text") or "",
            watched=_to_int(watched.get("num", 0)),
            likes=_to_int(like_info.get("total_likes", 0)),
            attention=_to_int(relation.get("attention", 0)),
            anchor_level=_to_int(live_info.get("level", 0)),
            medal_name=medal.get("medal_name") or "",
            fansclub=_to_int(medal.get("fansclub", 0)),
            guard_count=_to_int(guard_info.get("count", 0))
        )


class OpusImage(BaseModel):
    """B站图文中的一张正文图片。"""

    url: str = ""
    width: int = 0
    height: int = 0
    size: float = 0.0
    live_url: str = ""
    aigc: int = 0
    warning: Any | None = None
    comment: str = ""

    @classmethod
    def from_api(cls, data: dict | None) -> "OpusImage":
        data = data or {}
        return cls(
            url=data.get("url", "") or "",
            width=_opus_to_int(data.get("width")),
            height=_opus_to_int(data.get("height")),
            size=_opus_to_float(data.get("size")),
            live_url=data.get("live_url", "") or "",
            aigc=_opus_to_int(data.get("aigc")),
            warning=data.get("warning"),
            comment=data.get("comment", "") or "",
        )


class OpusAuthor(BaseModel):
    mid: int = 0
    name: str = ""
    face: str = ""
    pub_time: str = ""
    pub_ts: int = 0
    pub_location_text: str = ""
    official_title: str = ""
    is_vip: bool = False


class OpusTopic(BaseModel):
    id: str = ""
    name: str = ""
    jump_url: str = ""


class OpusLinkCard(BaseModel):
    """图文正文中的链接卡片。"""

    title: str = ""
    description: str = ""
    cover: str = ""
    jump_url: str = ""
    button_text: str = ""


class OpusContentBlock(BaseModel):
    """按正文顺序保存的文本、图片或链接卡片。"""

    type: Literal["text", "image", "link"]
    text: str = ""
    image: Optional[OpusImage] = None
    link: Optional[OpusLinkCard] = None


class OpusInfo(BaseModel):
    """用于 B站图文卡片渲染的稳定数据模型。"""

    opus_id: int
    title: str = ""
    author: OpusAuthor = Field(default_factory=OpusAuthor)
    topics: list[OpusTopic] = Field(default_factory=list)
    blocks: list[OpusContentBlock] = Field(default_factory=list)
    images: list[OpusImage] = Field(default_factory=list)
    emotes: dict[str, EmoteInfo] = Field(default_factory=dict)
    forward: int = 0
    comment: int = 0
    like: int = 0
    coin: int = 0
    favorite: int = 0

    @property
    def publish_time_str(self) -> str:
        if self.author.pub_time:
            return self.author.pub_time
        if self.author.pub_ts > 0:
            return datetime.fromtimestamp(self.author.pub_ts).strftime("%Y-%m-%d %H:%M")
        return ""

    @property
    def share_url(self) -> str:
        return f"https://www.bilibili.com/opus/{self.opus_id}"

    @staticmethod
    def format_count(value: int) -> str:
        return VideoInfo.format_count(value)

    @classmethod
    def from_api(cls, data: dict) -> "OpusInfo":
        """从 ``opus.Opus.get_info()`` 的原始响应构造。"""
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        item = data.get("item", data) or {}
        modules = item.get("modules", []) or []

        title = ""
        author = OpusAuthor()
        topics: list[OpusTopic] = []
        blocks: list[OpusContentBlock] = []
        images: list[OpusImage] = []
        emotes: dict[str, EmoteInfo] = {}
        stats: dict = {}

        for module in modules:
            if not isinstance(module, dict):
                continue

            title_data = module.get("module_title")
            if isinstance(title_data, dict) and not title:
                title = title_data.get("text", "") or ""

            author_data = module.get("module_author")
            if isinstance(author_data, dict):
                vip = author_data.get("vip", {}) or {}
                official = author_data.get("official", {}) or {}
                author = OpusAuthor(
                    mid=_opus_to_int(author_data.get("mid")),
                    name=author_data.get("name", "") or "",
                    face=author_data.get("face", "") or "",
                    pub_time=author_data.get("pub_time", "") or "",
                    pub_ts=_opus_to_int(author_data.get("pub_ts")),
                    pub_location_text=author_data.get("pub_location_text", "") or "",
                    official_title=official.get("title", "") or "",
                    is_vip=_opus_to_int(vip.get("status")) == 1,
                )

            topic_data = module.get("module_topic")
            if isinstance(topic_data, dict) and topic_data.get("name"):
                topics.append(OpusTopic(
                    id=str(topic_data.get("id", "") or ""),
                    name=topic_data.get("name", "") or "",
                    jump_url=topic_data.get("jump_url", "") or "",
                ))

            content = module.get("module_content")
            if isinstance(content, dict):
                for paragraph in content.get("paragraphs", []) or []:
                    if not isinstance(paragraph, dict):
                        continue
                    para_type = _opus_to_int(paragraph.get("para_type"))
                    if para_type == 1:
                        text, paragraph_emotes = _parse_opus_text(paragraph)
                        emotes.update(paragraph_emotes)
                        if text.strip():
                            blocks.append(OpusContentBlock(type="text", text=text.strip()))
                    elif para_type == 2:
                        pic_data = paragraph.get("pic", {}) or {}
                        for raw_image in pic_data.get("pics", []) or []:
                            image = OpusImage.from_api(raw_image)
                            if not image.url:
                                continue
                            images.append(image)
                            blocks.append(OpusContentBlock(type="image", image=image))
                    elif para_type == 7:
                        code = paragraph.get("code", {}) or {}
                        code_text = unescape(code.get("content", "") or "").strip()
                        if code_text:
                            blocks.append(OpusContentBlock(type="text", text=code_text))

                    link = _parse_opus_link_card(paragraph.get("link_card"))
                    if link is not None:
                        blocks.append(OpusContentBlock(type="link", link=link))

            stat_data = module.get("module_stat")
            if isinstance(stat_data, dict):
                stats = stat_data

        basic = item.get("basic", {}) or {}
        opus_id = _opus_to_int(item.get("id_str") or item.get("id"))
        if not title:
            title = basic.get("title", "") or ""

        def stat_count(name: str) -> int:
            value = stats.get(name, {}) or {}
            return _opus_to_int(value.get("count") if isinstance(value, dict) else value)

        return cls(
            opus_id=opus_id,
            title=title,
            author=author,
            topics=topics,
            blocks=blocks,
            images=images,
            emotes=emotes,
            forward=stat_count("forward"),
            comment=stat_count("comment"),
            like=stat_count("like"),
            coin=stat_count("coin"),
            favorite=stat_count("favorite"),
        )


def _parse_opus_text(paragraph: dict) -> tuple[str, dict[str, EmoteInfo]]:
    text_data = paragraph.get("text", {}) or {}
    parts: list[str] = []
    emotes: dict[str, EmoteInfo] = {}

    for node in text_data.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        word = node.get("word")
        if isinstance(word, dict):
            parts.append(word.get("words", "") or "")
            continue

        rich = node.get("rich")
        if isinstance(rich, dict):
            rich_text = rich.get("text") or rich.get("orig_text") or ""
            emoji = rich.get("emoji") or {}
            if emoji:
                rich_text = rich_text or emoji.get("text", "") or ""
                if rich_text:
                    emotes[rich_text] = EmoteInfo(
                        text=rich_text,
                        url=emoji.get("icon_url") or emoji.get("gif_url") or emoji.get("webp_url") or "",
                        size=_opus_to_int(emoji.get("size"), 1),
                    )
            parts.append(rich_text)
            continue

        user_data = node.get("user")
        if isinstance(user_data, dict):
            name = user_data.get("name") or user_data.get("uname") or ""
            if name:
                parts.append(f"@{name}")
            continue

        formula = node.get("formula")
        if isinstance(formula, dict):
            parts.append(formula.get("content") or formula.get("tex") or "")

    return "".join(parts), emotes


def _parse_opus_link_card(data: dict | None) -> OpusLinkCard | None:
    if not isinstance(data, dict):
        return None
    card = data.get("card", data) or {}
    payload = None
    for key in ("common", "ugc", "opus", "archive", "music", "live"):
        value = card.get(key)
        if isinstance(value, dict):
            payload = value
            break
    if not payload:
        return None

    button = payload.get("button", {}) or {}
    jump_style = button.get("jump_style", {}) or {}
    descriptions = [payload.get("desc1", ""), payload.get("desc2", ""), payload.get("desc", "")]
    return OpusLinkCard(
        title=payload.get("title", "") or payload.get("name", "") or "",
        description=" · ".join(str(value) for value in descriptions if value),
        cover=payload.get("cover", "") or payload.get("cover_url", "") or "",
        jump_url=payload.get("jump_url", "") or button.get("jump_url", "") or "",
        button_text=jump_style.get("text", "") or "",
    )


def _opus_to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _opus_to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
