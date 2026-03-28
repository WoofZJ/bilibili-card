from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DouyinUserInfo(BaseModel):
    """抖音用户信息模型"""
    uid: str
    sec_uid: str
    unique_id: str  # 抖音号
    nickname: str
    signature: str = ""  # 个人简介
    avatar: str = ""  # 头像URL
    gender: int = 0  # 0未知 1男 2女

    # 地理信息
    country: str = ""
    province: str = ""
    city: str = ""
    ip_location: str = ""

    # 数据统计
    follower_count: int = 0  # 粉丝数
    following_count: int = 0  # 关注数
    total_favorited: int = 0  # 获赞数
    favoriting_count: int = 0  # 喜欢数
    aweme_count: int = 0  # 作品数
    max_follower_count: int = 0  # 历史最高粉丝数

    # 其他
    user_age: int = 0
    custom_verify: str = ""  # 认证信息
    is_star: bool = False

    @property
    def gender_str(self) -> str:
        return {1: "男", 2: "女"}.get(self.gender, "未知")

    @staticmethod
    def format_count(n: int) -> str:
        if n >= 1000000:
            return f"{n / 10000:.0f}万"
        if n >= 10000:
            return f"{n / 10000:.1f}万"
        return str(n)

    @classmethod
    def from_api(cls, data: dict) -> "DouyinUserInfo":
        """从 DouyinAPI.get_user_info() 返回数据构造"""
        user = data.get("user", {})
        avatar_url = ""
        avatar_larger = user.get("avatar_larger", {})
        if avatar_larger and avatar_larger.get("url_list"):
            avatar_url = avatar_larger["url_list"][0]

        return cls(
            uid=str(user.get("uid", "")),
            sec_uid=user.get("sec_uid", ""),
            unique_id=user.get("unique_id", ""),
            nickname=user.get("nickname", ""),
            signature=user.get("signature", ""),
            avatar=avatar_url,
            gender=user.get("gender", 0),
            country=user.get("country", ""),
            province=user.get("province", ""),
            city=user.get("city", ""),
            ip_location=user.get("ip_location", ""),
            follower_count=user.get("follower_count", 0),
            following_count=user.get("following_count", 0),
            total_favorited=user.get("total_favorited", 0),
            favoriting_count=user.get("favoriting_count", 0),
            aweme_count=user.get("aweme_count", 0),
            max_follower_count=user.get("max_follower_count", 0),
            user_age=user.get("user_age", 0),
            custom_verify=user.get("custom_verify", ""),
            is_star=user.get("is_star", False),
        )


class DouyinWorkInfo(BaseModel):
    """抖音作品信息模型"""
    aweme_id: str
    desc: str = ""  # 作品描述
    create_time: int = 0  # Unix时间戳
    duration: int = 0  # 毫秒
    aweme_type: int = 0  # 0视频 68图文

    # 封面
    cover: str = ""  # 封面URL

    # 作者信息
    author_uid: str = ""
    author_sec_uid: str = ""
    author_nickname: str = ""
    author_avatar: str = ""

    # 视频分辨率
    width: int = 0
    height: int = 0

    # 数据统计
    digg_count: int = 0  # 点赞
    comment_count: int = 0  # 评论
    collect_count: int = 0  # 收藏
    share_count: int = 0  # 分享
    play_count: int = 0  # 播放

    # 音乐
    music_title: str = ""
    music_author: str = ""

    is_top: int = 0

    @property
    def duration_seconds(self) -> int:
        return self.duration // 1000

    @property
    def duration_str(self) -> str:
        """格式化时长 -> MM:SS 或 HH:MM:SS"""
        total = self.duration_seconds
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def create_time_str(self) -> str:
        return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M")

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"

    @staticmethod
    def format_count(n: int) -> str:
        if n >= 1000000:
            return f"{n / 10000:.0f}万"
        if n >= 10000:
            return f"{n / 10000:.1f}万"
        return str(n)

    @classmethod
    def from_api(cls, item: dict) -> "DouyinWorkInfo":
        """从单条作品数据构造"""
        author = item.get("author", {})
        statistics = item.get("statistics", {})
        video = item.get("video", {})
        music = item.get("music", {})

        # 封面
        cover_url = ""
        cover = video.get("cover", {})
        if cover and cover.get("url_list"):
            cover_url = cover["url_list"][0]

        # 作者头像
        author_avatar = ""
        avatar_thumb = author.get("avatar_thumb", {})
        if avatar_thumb and avatar_thumb.get("url_list"):
            author_avatar = avatar_thumb["url_list"][0]

        return cls(
            aweme_id=str(item.get("aweme_id", "")),
            desc=item.get("desc", ""),
            create_time=item.get("create_time", 0),
            duration=item.get("duration", 0),
            aweme_type=item.get("aweme_type", 0),
            cover=cover_url,
            author_uid=str(author.get("uid", "")),
            author_sec_uid=author.get("sec_uid", ""),
            author_nickname=author.get("nickname", ""),
            author_avatar=author_avatar,
            width=video.get("width", 0),
            height=video.get("height", 0),
            digg_count=statistics.get("digg_count", 0),
            comment_count=statistics.get("comment_count", 0),
            collect_count=statistics.get("collect_count", 0),
            share_count=statistics.get("share_count", 0),
            play_count=statistics.get("play_count", 0),
            music_title=music.get("title", ""),
            music_author=music.get("author", ""),
            is_top=item.get("is_top", 0),
        )

    @classmethod
    def from_api_list(cls, items: list) -> list["DouyinWorkInfo"]:
        """从作品列表数据构造"""
        return [cls.from_api(item) for item in items]


class DouyinCommentItem(BaseModel):
    """抖音单条评论"""
    cid: str  # 评论ID
    aweme_id: str = ""  # 作品ID
    nickname: str  # 用户名
    uid: str = ""  # 用户ID
    sec_uid: str = ""  # 用户sec_uid
    avatar: str = ""  # 头像URL
    text: str  # 评论内容
    digg_count: int = 0  # 点赞数
    create_time: int = 0  # 发布时间戳
    ip_label: str = ""  # IP属地
    is_hot: bool = False  # 是否热评
    is_author_digged: bool = False  # 作者是否点赞
    reply_comment_total: int = 0  # 回复数量
    level: int = 0  # 评论层级 1=一级 2=二级
    sticker_url: str = ""  # 表情贴纸URL
    sub_comments: list["DouyinCommentItem"] = []  # 子评论

    @property
    def create_time_str(self) -> str:
        if self.create_time:
            return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M")
        return ""

    @classmethod
    def from_api(cls, comment: dict) -> "DouyinCommentItem":
        """从单条评论数据构造"""
        user = comment.get("user", {})

        # 头像
        avatar_url = ""
        avatar_thumb = user.get("avatar_thumb", {})
        if avatar_thumb and avatar_thumb.get("url_list"):
            avatar_url = avatar_thumb["url_list"][0]

        # 表情贴纸
        sticker_url = ""
        sticker = comment.get("sticker", {})
        if sticker:
            static_url = sticker.get("static_url", {})
            if static_url and static_url.get("url_list"):
                sticker_url = static_url["url_list"][0]

        # 子评论
        sub_comments = []
        reply_comment = comment.get("reply_comment")
        if reply_comment and isinstance(reply_comment, list):
            for sub in reply_comment:
                sub_comments.append(cls.from_api(sub))

        return cls(
            cid=str(comment.get("cid", "")),
            aweme_id=str(comment.get("aweme_id", "")),
            nickname=user.get("nickname", ""),
            uid=str(user.get("uid", "")),
            sec_uid=user.get("sec_uid", ""),
            avatar=avatar_url,
            text=comment.get("text", ""),
            digg_count=comment.get("digg_count", 0),
            create_time=comment.get("create_time", 0),
            ip_label=comment.get("ip_label", ""),
            is_hot=comment.get("is_hot", False),
            is_author_digged=comment.get("is_author_digged", False),
            reply_comment_total=comment.get("reply_comment_total", 0),
            level=comment.get("level", 0),
            sticker_url=sticker_url,
            sub_comments=sub_comments,
        )


class DouyinCommentsData(BaseModel):
    """抖音评论数据"""
    total: int = 0  # 总评论数
    comments: list[DouyinCommentItem] = []  # 评论列表

    @classmethod
    def from_api(cls, data: dict) -> "DouyinCommentsData":
        """从 get_work_all_comment() 返回的评论列表构造"""
        # get_work_all_comment 返回的是 list
        if isinstance(data, list):
            comments = [DouyinCommentItem.from_api(c) for c in data]
            return cls(total=len(comments), comments=comments)

        # 原始 API 单页返回格式
        total = data.get("total", 0)
        raw_comments = data.get("comments", []) or []
        comments = [DouyinCommentItem.from_api(c) for c in raw_comments]
        return cls(total=total, comments=comments)
