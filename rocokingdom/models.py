from datetime import date, datetime, timedelta
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_TIMEZONE = "Asia/Shanghai"
ROUND_START_HOUR = 8
ROUND_DURATION_HOURS = 4
ROUND_COUNT = 4


class RocoMerchantItem(BaseModel):
    """远行商人 ``get_props`` 中的一件商品。"""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default="", alias="_id")
    end_time: int = 0
    icon_url: str = ""
    name: str = ""
    round: int = 0
    start_time: int = 0
    limit: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any], *, limit: int = 0) -> "RocoMerchantItem":
        return cls(
            _id=_first_text(data.get("_id"), data.get("id")),
            end_time=_to_int(data.get("end_time")),
            icon_url=unescape(_first_text(data.get("icon_url"))),
            name=_first_text(data.get("name")),
            round=_to_int(data.get("round")),
            start_time=_to_int(data.get("start_time")),
            limit=limit,
        )

    @property
    def time_range_text(self) -> str:
        if self.round == 0:
            return "08:00 ~ 24:00"
        if 1 <= self.round <= ROUND_COUNT:
            start_hour = ROUND_START_HOUR + (self.round - 1) * ROUND_DURATION_HOURS
            end_hour = start_hour + ROUND_DURATION_HOURS
            return f"{start_hour:02d}:00 ~ {end_hour:02d}:00"
        return "售卖时间待定"


class RocoMerchantResult(BaseModel):
    """供远行商人接口和卡片渲染使用的标准化结果。"""

    source_url: str = ""
    fetched_at: str = ""
    timezone: str = DEFAULT_TIMEZONE
    status: str = ""
    round: int | None = None
    started_at_beijing: str = ""
    next_refresh_beijing: str = ""
    duration_hours: float = 0
    merchant_position: str = ""
    items: list[RocoMerchantItem] = Field(default_factory=list)
    rounds: dict[int, list[RocoMerchantItem]] = Field(default_factory=dict)
    live: bool = False

    @property
    def started_at(self) -> datetime | None:
        return _parse_datetime(self.started_at_beijing, self.timezone)

    @property
    def next_refresh_at(self) -> datetime | None:
        return _parse_datetime(self.next_refresh_beijing, self.timezone)

    @property
    def status_text(self) -> str:
        return "售卖中" if self.live else "进货中"

    @property
    def round_name(self) -> str:
        if self.round is not None:
            return f"round_{self.round}"
        return "closed"

    @property
    def date_text(self) -> str:
        dt = self.started_at or self.next_refresh_at
        return dt.strftime("%Y-%m-%d") if dt else ""

    @property
    def short_date_text(self) -> str:
        dt = self.started_at or self.next_refresh_at
        return dt.strftime("%m.%d") if dt else ""

    @property
    def time_range_text(self) -> str:
        if self.live and self.round is not None:
            start_hour = ROUND_START_HOUR + (self.round - 1) * ROUND_DURATION_HOURS
            end_hour = start_hour + ROUND_DURATION_HOURS
            return f"{start_hour:02d}:00 ~ {end_hour:02d}:00"
        start = self.started_at
        next_refresh = self.next_refresh_at
        if start and next_refresh and self.live:
            return f"{start:%H:%M} ~ {next_refresh:%H:%M}"
        return self.next_refresh_text

    @property
    def next_refresh_text(self) -> str:
        next_refresh = self.next_refresh_at
        if next_refresh:
            return f"下次出现于 {next_refresh:%m月%d日 %H:%M}"
        return ""

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> "RocoMerchantResult":
        """将新接口的 ``data.merchantActivities[].get_props`` 转为渲染模型。"""
        timezone = DEFAULT_TIMEZONE
        tz = _get_timezone(timezone)
        current_time = now or datetime.now(tz)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=tz)
        else:
            current_time = current_time.astimezone(tz)

        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        activities = payload.get("merchantActivities", []) or []
        activities = [activity for activity in activities if isinstance(activity, dict)]
        activity = _select_activity(activities, current_time)

        if activity is None:
            return cls(
                fetched_at=current_time.isoformat(),
                timezone=timezone,
                status="closed",
            )

        limits = {
            _first_text(good.get("goods_name")): _to_int(good.get("buy_limit_num"))
            for good in payload.get("random_goods", []) or []
            if isinstance(good, dict) and good.get("goods_name")
        }
        props = [
            RocoMerchantItem.from_api(
                prop,
                limit=limits.get(_first_text(prop.get("name")), 0),
            )
            for prop in activity.get("get_props", []) or []
            if isinstance(prop, dict)
        ]
        props.sort(key=lambda item: (item.round, item.start_time, item.name))

        rounds: dict[int, list[RocoMerchantItem]] = {}
        for item in props:
            rounds.setdefault(item.round, []).append(item)

        activity_date = _parse_date(_first_text(activity.get("start_date")))
        current_round = _round_at(current_time) if current_time.date() == activity_date else None
        live = current_round is not None
        active_items = [item for item in props if live and item.round in {0, current_round}]

        period_start = None
        period_end = None
        if activity_date and current_round is not None:
            start_hour = ROUND_START_HOUR + (current_round - 1) * ROUND_DURATION_HOURS
            period_start = datetime.combine(
                activity_date,
                datetime.min.time(),
                tzinfo=tz,
            ).replace(hour=start_hour)
            period_end = period_start + timedelta(hours=ROUND_DURATION_HOURS)
        elif activity_date and current_time.date() < activity_date:
            period_end = datetime.combine(
                activity_date,
                datetime.min.time(),
                tzinfo=tz,
            ).replace(hour=ROUND_START_HOUR)
        elif activity_date and current_time.date() == activity_date and current_time.hour < ROUND_START_HOUR:
            period_end = current_time.replace(
                hour=ROUND_START_HOUR,
                minute=0,
                second=0,
                microsecond=0,
            )

        return cls(
            fetched_at=current_time.isoformat(),
            timezone=timezone,
            status="open" if live else "closed",
            round=current_round,
            started_at_beijing=_format_datetime(period_start),
            next_refresh_beijing=_format_datetime(period_end),
            duration_hours=ROUND_DURATION_HOURS if live else 0,
            items=active_items,
            rounds=rounds,
            live=live,
        )


def _select_activity(
    activities: list[dict[str, Any]],
    current_time: datetime,
) -> dict[str, Any] | None:
    if not activities:
        return None
    for activity in activities:
        if _parse_date(_first_text(activity.get("start_date"))) == current_time.date():
            return activity
    upcoming = [
        activity for activity in activities
        if (_parse_date(_first_text(activity.get("start_date"))) or current_time.date())
        > current_time.date()
    ]
    if upcoming:
        return min(upcoming, key=lambda value: _first_text(value.get("start_date")))
    return max(activities, key=lambda value: _first_text(value.get("start_date")))


def _parse_datetime(value: str, timezone: str = DEFAULT_TIMEZONE) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_get_timezone(timezone))
    return parsed


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _round_at(value: datetime) -> int | None:
    if not ROUND_START_HOUR <= value.hour < ROUND_START_HOUR + ROUND_COUNT * ROUND_DURATION_HOURS:
        return None
    return (value.hour - ROUND_START_HOUR) // ROUND_DURATION_HOURS + 1


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _first_text(*values) -> str:
    for value in values:
        if value is not None and value != "":
            return str(value)
    return ""


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
