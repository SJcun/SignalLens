"""AI 分析任务的北京时间窗口计算。"""

from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

ANALYSIS_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_ANALYSIS_WINDOWS = [{"start": "00:00", "end": "08:00"}]


def parse_clock(value: str) -> time:
    """解析 API 使用的 24 小时制时分。"""

    return time.fromisoformat(value)


def validate_windows(windows: list[dict[str, str]]) -> None:
    """拒绝空区间和互相重叠的每日窗口，避免执行规则含糊。"""

    expanded: list[tuple[int, int]] = []
    for window in windows:
        start = _minute_of_day(window["start"])
        end = _minute_of_day(window["end"])
        if start == end:
            raise ValueError("整理时段的开始和结束时间不能相同")
        if start < end:
            expanded.append((start, end))
        else:
            # 跨午夜窗口拆成当天尾部和次日开头，便于统一检查重叠。
            expanded.append((start, 24 * 60))
            if end:
                expanded.append((0, end))

    expanded.sort()
    for previous, current in pairwise(expanded):
        if current[0] < previous[1]:
            raise ValueError("整理时段不能互相重叠")


def is_within_windows(now: datetime, windows: list[dict[str, str]]) -> bool:
    """判断给定时刻是否位于任一北京时间窗口内。"""

    local_now = _as_utc(now).astimezone(ANALYSIS_TIMEZONE)
    current = (
        local_now.hour * 60
        + local_now.minute
        + local_now.second / 60
        + local_now.microsecond / 60_000_000
    )
    for window in windows:
        start = _minute_of_day(window["start"])
        end = _minute_of_day(window["end"])
        if start < end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False


def next_window_start(
    now: datetime,
    windows: list[dict[str, str]],
) -> datetime | None:
    """返回下一次窗口开始时间的 UTC 时刻。"""

    if not windows:
        return None
    local_now = _as_utc(now).astimezone(ANALYSIS_TIMEZONE)
    candidates: list[datetime] = []
    for day_offset in range(3):
        target_date = local_now.date() + timedelta(days=day_offset)
        for window in windows:
            candidate = datetime.combine(
                target_date,
                parse_clock(window["start"]),
                tzinfo=ANALYSIS_TIMEZONE,
            )
            if candidate > local_now:
                candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates).astimezone(UTC)


def _minute_of_day(value: str) -> int:
    """将时分转换为便于比较的当天分钟数。"""

    parsed = parse_clock(value)
    return parsed.hour * 60 + parsed.minute


def _as_utc(value: datetime) -> datetime:
    """按照项目约定为 SQLite 的 naive 时间补充 UTC 语义。"""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
