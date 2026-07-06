from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NeteaseArtist(BaseModel):
    """网易云歌手信息"""

    id: int = 0
    name: str = ""
    aliases: list[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "NeteaseArtist":
        return cls(
            id=_to_int(data.get("id")),
            name=_first_text(data.get("name")),
            aliases=_str_list(data.get("alias") or data.get("tns")),
        )


class NeteaseAlbum(BaseModel):
    """网易云专辑信息"""

    id: int = 0
    name: str = ""
    pic: int = 0
    pic_url: str = ""
    aliases: list[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "NeteaseAlbum":
        return cls(
            id=_to_int(data.get("id")),
            name=_first_text(data.get("name")),
            pic=_to_int(data.get("pic")),
            pic_url=_first_text(data.get("picUrl"), data.get("pic_url")),
            aliases=_str_list(data.get("tns") or data.get("alias")),
        )


class NeteaseQualityInfo(BaseModel):
    """歌曲某一档音质的文件信息"""

    bitrate: int = 0
    size: int = 0
    volume_delta: int = 0
    sample_rate: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any] | None) -> "NeteaseQualityInfo":
        data = data or {}
        return cls(
            bitrate=_to_int(data.get("br")),
            size=_to_int(data.get("size")),
            volume_delta=_to_int(data.get("vd")),
            sample_rate=_to_int(data.get("sr")),
        )


class NeteasePrivilege(BaseModel):
    """网易云播放权限信息"""

    id: int = 0
    fee: int = 0
    payed: int = 0
    status: int = 0
    play_level: int = 0
    download_level: int = 0
    max_bitrate: int = 0
    actual_bitrate: int = 0
    play_max_bitrate: int = 0
    download_max_bitrate: int = 0
    toast: bool = False
    flag: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any] | None) -> "NeteasePrivilege":
        data = data or {}
        return cls(
            id=_to_int(data.get("id")),
            fee=_to_int(data.get("fee")),
            payed=_to_int(data.get("payed")),
            status=_to_int(data.get("st")),
            play_level=_to_int(data.get("pl")),
            download_level=_to_int(data.get("dl")),
            max_bitrate=_to_int(data.get("maxbr")),
            actual_bitrate=_to_int(data.get("fl")),
            play_max_bitrate=_to_int(data.get("playMaxbr")),
            download_max_bitrate=_to_int(data.get("downloadMaxbr")),
            toast=bool(data.get("toast")),
            flag=_to_int(data.get("flag")),
        )


class NeteaseDownloadInfo(BaseModel):
    """网易云歌曲播放/下载链接信息"""

    id: int = 0
    url: str = ""
    level: str = ""
    quality_name: str = ""
    type: str = ""
    encode_type: str = ""
    size: int = 0
    size_formatted: str = ""
    bitrate: int = 0
    md5: str = ""
    code: int = 0
    free_trial: bool = False
    available: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any], requested_level: str = "lossless") -> "NeteaseDownloadInfo":
        items = data.get("data") or []
        item = items[0] if items and isinstance(items[0], dict) else {}
        level = _first_text(item.get("level"), requested_level)
        size = _to_int(item.get("size"))
        free_trial_privilege = item.get("freeTrialPrivilege")
        if not isinstance(free_trial_privilege, dict):
            free_trial_privilege = {}

        return cls(
            id=_to_int(item.get("id")),
            url=_first_text(item.get("url")),
            level=level,
            quality_name=_quality_display_name(level),
            type=_first_text(item.get("type")),
            encode_type=_first_text(item.get("encodeType"), item.get("encode_type")),
            size=size,
            size_formatted=_format_file_size(size),
            bitrate=_to_int(item.get("br")),
            md5=_first_text(item.get("md5")),
            code=_to_int(item.get("code")),
            free_trial=bool(item.get("freeTrialInfo") or free_trial_privilege.get("resConsumable")),
            available=bool(item.get("url")),
        )


class NeteaseLyricInfo(BaseModel):
    """网易云歌词信息"""

    lyric: str = ""
    translated_lyric: str = ""
    roman_lyric: str = ""
    klyric: str = ""
    yrc: str = ""
    has_lyric: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "NeteaseLyricInfo":
        lyric = _first_text((data.get("lrc") or {}).get("lyric"))
        translated_lyric = _first_text((data.get("tlyric") or {}).get("lyric"))
        roman_lyric = _first_text((data.get("romalrc") or {}).get("lyric"))
        klyric = _first_text((data.get("klyric") or {}).get("lyric"))
        yrc = _first_text((data.get("yrc") or {}).get("lyric"))

        return cls(
            lyric=lyric,
            translated_lyric=translated_lyric,
            roman_lyric=roman_lyric,
            klyric=klyric,
            yrc=yrc,
            has_lyric=bool(lyric or translated_lyric or roman_lyric or klyric or yrc),
        )


class NeteaseSongInfo(BaseModel):
    """网易云单曲信息"""

    id: int
    name: str
    aliases: list[str] = Field(default_factory=list)
    artists: list[NeteaseArtist] = Field(default_factory=list)
    artist_names: str = ""
    album: NeteaseAlbum = Field(default_factory=NeteaseAlbum)
    album_name: str = ""
    cover: str = ""
    duration: int = 0
    duration_seconds: int = 0
    duration_str: str = ""
    disc: str = ""
    track_number: int = 0
    popularity: int = 0
    mv_id: int = 0
    fee: int = 0
    copyright: int = 0
    publish_time: int = 0
    publish_time_str: str = ""
    comment_thread_id: str = ""
    source_url: str = ""
    qualities: dict[str, NeteaseQualityInfo] = Field(default_factory=dict)
    privilege: NeteasePrivilege | None = None
    download: NeteaseDownloadInfo | None = None
    lyrics: NeteaseLyricInfo = Field(default_factory=NeteaseLyricInfo)
    download_error: str = ""
    lyric_error: str = ""

    # 兼容旧 Flask 页面 type=json 的字段命名
    url: str = ""
    level: str = ""
    size: str = ""
    lyric: str = ""
    tlyric: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "NeteaseSongInfo":
        """从 /api/v3/song/detail 响应或单个 song 字典构造模型。"""
        if "songs" in data:
            songs = data.get("songs") or []
            if not songs:
                raise ValueError("歌曲详情为空")
            song = songs[0]
            if not isinstance(song, dict) or not song.get("id"):
                raise ValueError("歌曲详情为空")
            privileges = data.get("privileges") or []
        else:
            song = data
            if not isinstance(song, dict) or not song.get("id"):
                raise ValueError("歌曲详情为空")
            privileges = []

        song_id = _to_int(song.get("id"))
        artists = [
            NeteaseArtist.from_api(item)
            for item in (song.get("ar") or song.get("artists") or [])
            if isinstance(item, dict)
        ]
        album = NeteaseAlbum.from_api(song.get("al") or song.get("album") or {})
        duration = _to_int(song.get("dt") or song.get("duration"))
        publish_time = _to_int(song.get("publishTime") or song.get("publish_time"))
        privilege = _match_privilege(song_id, privileges)

        qualities = {}
        for key in ("h", "m", "l", "sq", "hr"):
            value = song.get(key)
            if isinstance(value, dict):
                qualities[key] = NeteaseQualityInfo.from_api(value)

        return cls(
            id=song_id,
            name=_first_text(song.get("name")),
            aliases=_str_list(song.get("alia") or song.get("alias")),
            artists=artists,
            artist_names="/".join(artist.name for artist in artists if artist.name),
            album=album,
            album_name=album.name,
            cover=album.pic_url,
            duration=duration,
            duration_seconds=duration // 1000 if duration > 0 else 0,
            duration_str=_format_duration(duration),
            disc=_first_text(song.get("cd")),
            track_number=_to_int(song.get("no")),
            popularity=_to_int(song.get("pop")),
            mv_id=_to_int(song.get("mv")),
            fee=_to_int(song.get("fee")),
            copyright=_to_int(song.get("copyright")),
            publish_time=publish_time,
            publish_time_str=_format_timestamp_ms(publish_time),
            comment_thread_id=f"R_SO_4_{song_id}" if song_id else "",
            source_url=f"https://music.163.com/#/song?id={song_id}" if song_id else "",
            qualities=qualities,
            privilege=privilege,
        )


def _match_privilege(song_id: int, privileges: list[Any]) -> NeteasePrivilege | None:
    if not privileges:
        return None
    for item in privileges:
        if isinstance(item, dict) and _to_int(item.get("id")) == song_id:
            return NeteasePrivilege.from_api(item)
    first = privileges[0]
    return NeteasePrivilege.from_api(first) if isinstance(first, dict) else None


def _format_duration(duration_ms: int) -> str:
    if duration_ms <= 0:
        return "00:00"
    total_seconds = duration_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_timestamp_ms(value: int) -> str:
    if value <= 0:
        return ""
    timestamp = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _format_file_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.2f}{units[unit_index]}"


def _quality_display_name(quality: str) -> str:
    return {
        "standard": "标准音质",
        "exhigh": "极高音质",
        "lossless": "无损音质",
        "hires": "Hi-Res音质",
        "sky": "沉浸环绕声",
        "jyeffect": "高清环绕声",
        "jymaster": "超清母带",
        "dolby": "杜比全景声",
    }.get(quality, f"未知音质({quality})")


def _str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and item != ""]
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and value != "":
            return str(value)
    return ""


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
