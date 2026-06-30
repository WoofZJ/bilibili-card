from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RocoMerchantItem(BaseModel):
    """远行商人商品信息"""

    name: str = ""
    price: str = ""
    price_raw: str = ""
    limit: str = ""
    image: str = ""
    category: str = ""
    description: str = ""
    rounds: list[int] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "RocoMerchantItem":
        return cls(
            name=_first_text(data.get("name")),
            price=_first_text(data.get("price")),
            price_raw=_first_text(data.get("priceRaw"), data.get("price_raw"), data.get("price")),
            limit=_first_text(data.get("limit")),
            image=_first_text(data.get("image")),
            category=_first_text(data.get("category")),
            description=_first_text(data.get("description")),
            rounds=[_to_int(value) for value in data.get("rounds", []) or []],
        )


class RocoMerchantResult(BaseModel):
    """洛克王国远行商人信息"""

    source_url: str = ""
    fetched_at: str = ""
    timezone: str = "Asia/Shanghai"
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
        return _parse_datetime(self.started_at_beijing)

    @property
    def next_refresh_at(self) -> datetime | None:
        return _parse_datetime(self.next_refresh_beijing)

    @property
    def status_text(self) -> str:
        if self.items and self.round is not None:
            return "售卖中"
        return "进货中"

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
        start = self.started_at
        next_refresh = self.next_refresh_at
        if start and next_refresh:
            return f"{start:%H:%M} ~ {next_refresh:%H:%M}"
        return self.next_refresh_text

    @property
    def next_refresh_text(self) -> str:
        next_refresh = self.next_refresh_at
        if next_refresh:
            return f"下次出现于 {next_refresh:%m月%d日 %H:%M}"
        return ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "RocoMerchantResult":
        items = [RocoMerchantItem.from_api(item) for item in data.get("items", []) or []]
        rounds: dict[int, list[RocoMerchantItem]] = {}
        for key, value in (data.get("rounds") or {}).items():
            round_no = _to_int(key)
            rounds[round_no] = [
                RocoMerchantItem.from_api(item)
                for item in value or []
                if isinstance(item, dict)
            ]

        return cls(
            source_url=_first_text(data.get("sourceUrl"), data.get("source_url")),
            fetched_at=_first_text(data.get("fetchedAt"), data.get("fetched_at")),
            timezone=_first_text(data.get("timezone")) or "Asia/Shanghai",
            status=_first_text(data.get("status")),
            round=_optional_int(data.get("round")),
            started_at_beijing=_first_text(data.get("startedAtBeijing"), data.get("started_at_beijing")),
            next_refresh_beijing=_first_text(data.get("nextRefreshBeijing"), data.get("next_refresh_beijing")),
            duration_hours=_to_float(data.get("durationHours") or data.get("duration_hours")),
            merchant_position=_first_text(data.get("merchantPosition"), data.get("merchant_position")),
            items=items,
            rounds=rounds,
            live=_to_bool(data.get("live", bool(items))),
        )


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return _to_int(value)


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


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)
