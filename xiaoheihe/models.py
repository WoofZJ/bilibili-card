import json
import re
from datetime import datetime
from html import unescape
from typing import Any, Literal, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field


class XiaoheiheImage(BaseModel):
    """小黑盒正文或评论图片"""
    url: str = ""
    width: int = 0
    height: int = 0


class XiaoheiheEmote(BaseModel):
    """小黑盒评论内联表情"""
    text: str = ""
    code: str = ""
    group_code: str = ""
    name: str = ""
    url: str = ""
    type: int = 0


class XiaoheiheMedal(BaseModel):
    medal_id: int = 0
    name: str = ""
    description: str = ""
    img_url: str = ""
    level: int = 0
    achieved: int = 0
    wear: int = 0


class XiaoheiheUser(BaseModel):
    userid: int = 0
    username: str = ""
    avatar: str = ""
    level: int = 0
    medals: list[XiaoheiheMedal] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict | None) -> "XiaoheiheUser":
        data = data or {}
        level_info = data.get("level_info", {}) or {}
        medals = []
        for item in data.get("medals", []) or data.get("medal", []) or []:
            medals.append(XiaoheiheMedal(
                medal_id=_to_int(item.get("medal_id")),
                name=item.get("name", "") or "",
                description=item.get("description", "") or "",
                img_url=item.get("img_url", "") or "",
                level=_to_int(item.get("level")),
                achieved=_to_int(item.get("achieved")),
                wear=_to_int(item.get("wear")),
            ))

        return cls(
            userid=_to_int(data.get("userid")),
            username=data.get("username", "") or "",
            avatar=data.get("avatar") or data.get("avartar") or "",
            level=_to_int(level_info.get("level")),
            medals=medals,
        )


class XiaoheiheTopic(BaseModel):
    topic_id: int = 0
    name: str = ""
    pic_url: str = ""
    hot_value: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "XiaoheiheTopic":
        return cls(
            topic_id=_to_int(data.get("topic_id")),
            name=data.get("name", "") or data.get("text", "") or "",
            pic_url=data.get("pic_url", "") or data.get("icon", "") or "",
            hot_value=_to_int(data.get("hot_value_v2")),
        )


class XiaoheihePostBlock(BaseModel):
    type: Literal["text", "image"]
    text: str = ""
    image: Optional[XiaoheiheImage] = None


class XiaoheihePostInfo(BaseModel):
    """小黑盒博文信息"""
    link_id: str
    internal_id: int = 0
    title: str = ""
    description: str = ""
    raw_text: str = ""
    plain_text: str = ""
    blocks: list[XiaoheihePostBlock] = Field(default_factory=list)
    images: list[XiaoheiheImage] = Field(default_factory=list)
    author: XiaoheiheUser = Field(default_factory=XiaoheiheUser)
    create_at: int = 0
    ip_location: str = ""
    comment_num: int = 0
    favour_count: int = 0
    forward_num: int = 0
    up: int = 0
    topics: list[XiaoheiheTopic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    share_url: str = ""

    @property
    def create_time_str(self) -> str:
        if self.create_at <= 0:
            return ""
        return datetime.fromtimestamp(self.create_at).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def format_count(value: int) -> str:
        if value >= 100000000:
            return f"{value / 100000000:.1f}亿"
        if value >= 10000:
            return f"{value / 10000:.1f}万"
        return str(value)

    @classmethod
    def from_api(cls, data: dict) -> "XiaoheihePostInfo":
        link = data.get("link", data) or {}
        blocks, images, plain_text = _parse_link_text(link.get("text", ""))
        topics = [XiaoheiheTopic.from_api(t) for t in link.get("topics", []) or []]
        content_tags = link.get("content_tags", []) or []
        tags = [
            tag.get("text", "")
            for tag in content_tags
            if isinstance(tag, dict) and tag.get("text")
        ]

        return cls(
            link_id=_extract_share_link_id(link.get("share_url", "")) or str(link.get("link_id") or link.get("linkid") or ""),
            internal_id=_to_int(link.get("linkid")),
            title=link.get("title", "") or "",
            description=link.get("description", "") or plain_text[:180],
            raw_text=link.get("text", "") or "",
            plain_text=plain_text,
            blocks=blocks,
            images=images,
            author=XiaoheiheUser.from_api(link.get("user")),
            create_at=_to_int(link.get("create_at")),
            ip_location=link.get("ip_location", "") or "",
            comment_num=_to_int(link.get("comment_num")),
            favour_count=_to_int(link.get("favour_count")),
            forward_num=_to_int(link.get("forward_num")),
            up=_to_int(link.get("up")),
            topics=topics,
            tags=tags,
            share_url=link.get("share_url", "") or "",
        )


class XiaoheiheCommentItem(BaseModel):
    """小黑盒单条评论"""
    comment_id: int = 0
    user: XiaoheiheUser = Field(default_factory=XiaoheiheUser)
    text: str = ""
    create_at: int = 0
    ip_location: str = ""
    up: int = 0
    child_num: int = 0
    floor_num: int = 0
    is_top: bool = False
    is_link_owner: bool = False
    reply_id: int = 0
    reply_user_id: int = 0
    reply_user: Optional[XiaoheiheUser] = None
    sub_comments: list["XiaoheiheCommentItem"] = Field(default_factory=list)

    @property
    def create_time_str(self) -> str:
        if self.create_at <= 0:
            return ""
        return datetime.fromtimestamp(self.create_at).strftime("%Y-%m-%d %H:%M")

    @classmethod
    def from_api(cls, data: dict) -> "XiaoheiheCommentItem":
        replyuser = data.get("replyuser")
        return cls(
            comment_id=_to_int(data.get("commentid")),
            user=XiaoheiheUser.from_api(data.get("user")),
            text=data.get("text", "") or "",
            create_at=_to_int(data.get("create_at")),
            ip_location=data.get("ip_location", "") or "",
            up=_to_int(data.get("up")),
            child_num=_to_int(data.get("child_num")),
            floor_num=_to_int(data.get("floor_num")),
            is_top=bool(_to_int(data.get("is_top"))),
            is_link_owner=bool(_to_int(data.get("is_link_owner"))),
            reply_id=_to_int(data.get("replyid")),
            reply_user_id=_to_int(data.get("replyuserid")),
            reply_user=XiaoheiheUser.from_api(replyuser) if replyuser else None,
        )


class XiaoheiheCommentsData(BaseModel):
    """小黑盒评论列表"""
    link_id: str = ""
    total: int = 0
    total_floor_num: int = 0
    total_page: int = 0
    has_more: bool = False
    emotes: dict[str, XiaoheiheEmote] = Field(default_factory=dict)
    comments: list[XiaoheiheCommentItem] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "XiaoheiheCommentsData":
        result = data.get("result", data) or {}
        link = result.get("link", {}) or {}
        comments = []
        for group in result.get("comments", []) or []:
            items = group.get("comment", []) or []
            if not items:
                continue
            root = XiaoheiheCommentItem.from_api(items[0])
            root.sub_comments = [
                XiaoheiheCommentItem.from_api(item)
                for item in items[1:]
            ]
            comments.append(root)

        return cls(
            link_id=_extract_share_link_id(link.get("share_url", "")) or str(link.get("link_id") or link.get("linkid") or ""),
            total=_to_int(link.get("comment_num")) or sum(1 + len(c.sub_comments) for c in comments),
            total_floor_num=_to_int(result.get("total_floor_num")),
            total_page=_to_int(result.get("total_page")),
            has_more=bool(_to_int(result.get("has_more_floors"))),
            comments=comments,
        )


def parse_xiaoheihe_emotes(data: dict) -> dict[str, XiaoheiheEmote]:
    """从 /bbs/app/api/emojis/list 响应中提取 [cube_xxx] 表情映射"""
    result = data.get("result", data) or {}
    emotes: dict[str, XiaoheiheEmote] = {}

    for group in result.get("emoji_groups", []) or []:
        if not isinstance(group, dict):
            continue
        group_code = str(group.get("group_code") or "").strip()
        if not group_code:
            continue

        for item in group.get("emojis", []) or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("name") or "").strip()
            url = item.get("img") or item.get("url") or ""
            if not code or not url:
                continue

            token_code = code if code.startswith(f"{group_code}_") else f"{group_code}_{code}"
            text = f"[{token_code}]"
            emotes[text] = XiaoheiheEmote(
                text=text,
                code=code,
                group_code=group_code,
                name=item.get("name", "") or "",
                url=url,
                type=_to_int(item.get("type") or group.get("type")),
            )

    return emotes


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_link_text(raw_text: str) -> tuple[list[XiaoheihePostBlock], list[XiaoheiheImage], str]:
    if not raw_text:
        return [], [], ""

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        plain = _html_to_text(raw_text)
        return [XiaoheihePostBlock(type="text", text=plain)] if plain else [], [], plain

    if not isinstance(parsed, list):
        plain = _html_to_text(str(parsed))
        return [XiaoheihePostBlock(type="text", text=plain)] if plain else [], [], plain

    blocks: list[XiaoheihePostBlock] = []
    images: list[XiaoheiheImage] = []
    seen_images: set[str] = set()
    explicit_images = [
        XiaoheiheImage(
            url=item.get("url", "") or "",
            width=_to_int(item.get("width")),
            height=_to_int(item.get("height")),
        )
        for item in parsed
        if isinstance(item, dict) and item.get("type") == "img" and item.get("url")
    ]
    explicit_index = 0

    for item in parsed:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "html":
            html_blocks, _ = _parse_html_blocks(item.get("text", "") or "")
            for block in html_blocks:
                if block.type == "image" and explicit_index < len(explicit_images):
                    image = explicit_images[explicit_index]
                    explicit_index += 1
                    block = XiaoheihePostBlock(type="image", image=image)
                blocks.append(block)

    for block in blocks:
        if block.type == "image" and block.image and block.image.url:
            key = _image_key(block.image.url)
            if key not in seen_images:
                seen_images.add(key)
                images.append(block.image)

    if not any(block.type == "image" for block in blocks):
        for image in explicit_images:
            key = _image_key(image.url)
            if image.url and key not in seen_images:
                seen_images.add(key)
                images.append(image)
                blocks.append(XiaoheihePostBlock(type="image", image=image))

    plain_text = "\n".join(
        block.text.strip()
        for block in blocks
        if block.type == "text" and block.text.strip()
    )
    return blocks, images, plain_text


def _parse_html_blocks(html: str) -> tuple[list[XiaoheihePostBlock], list[XiaoheiheImage]]:
    soup = BeautifulSoup(unescape(html), "lxml")
    blocks: list[XiaoheihePostBlock] = []
    images: list[XiaoheiheImage] = []
    roots = soup.body.contents if soup.body else soup.contents

    for node in roots:
        name = getattr(node, "name", None)
        if name == "p":
            img = node.find("img")
            if img:
                image = XiaoheiheImage(
                    url=img.get("data-original") or img.get("src") or "",
                    width=_to_int(img.get("data-width") or img.get("width")),
                    height=_to_int(img.get("data-height") or img.get("height")),
                )
                if image.url:
                    images.append(image)
                    blocks.append(XiaoheihePostBlock(type="image", image=image))
                continue
            text = _normalize_text(node.get_text(" ", strip=True))
            if text:
                blocks.append(XiaoheihePostBlock(type="text", text=text))
        else:
            text = _normalize_text(getattr(node, "get_text", lambda *args, **kwargs: str(node))(" ", strip=True))
            if text:
                blocks.append(XiaoheihePostBlock(type="text", text=text))

    return blocks, images


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(unescape(html), "lxml")
    return _normalize_text(soup.get_text("\n", strip=True))


def _normalize_text(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _extract_share_link_id(share_url: str) -> str:
    if not share_url:
        return ""
    query = parse_qs(urlparse(share_url).query)
    if "link_id" in query and query["link_id"]:
        return query["link_id"][0]
    match = re.search(r"/(?:app/bbs/link|bbs/link|link)/([0-9a-fA-F]+)", share_url)
    return match.group(1) if match else ""


def _image_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if "/bbs/" in path:
        return path[path.index("/bbs/"):]
    return path or url
