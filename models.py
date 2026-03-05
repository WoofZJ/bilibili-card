from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class EmoteInfo(BaseModel):
    """表情包信息"""
    text: str  # 表情文本，如 "[doge]"
    url: str = ""  # 表情图片URL
    size: int = 1  # 1=小表情(行内), 2=大表情


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
        return f"最高分辨率：{self.width}x{self.height}"

    @staticmethod
    def format_count(n: int) -> str:
        """格式化数字：超过1万显示 x.x万"""
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
        )
