"""AI 整理窗口的纯时间计算回归。"""

from datetime import UTC, datetime

import pytest

from signallens.scheduling import (
    is_within_windows,
    next_window_start,
    validate_windows,
)


def test_daily_and_cross_midnight_windows_use_shanghai_time() -> None:
    """普通窗口和跨午夜窗口都按北京时间判断，结束边界不放行。"""

    daytime = [{"start": "01:00", "end": "08:00"}]
    assert is_within_windows(datetime(2026, 8, 13, 17, 0, tzinfo=UTC), daytime) is True
    assert is_within_windows(datetime(2026, 8, 14, 0, 0, tzinfo=UTC), daytime) is False

    overnight = [{"start": "23:00", "end": "06:00"}]
    assert is_within_windows(datetime(2026, 8, 13, 16, 0, tzinfo=UTC), overnight) is True
    assert is_within_windows(datetime(2026, 8, 13, 22, 0, tzinfo=UTC), overnight) is False


def test_next_window_start_returns_utc() -> None:
    """窗口外返回下一次北京时间开始点对应的 UTC。"""

    result = next_window_start(
        datetime(2026, 8, 14, 4, 0, tzinfo=UTC),
        [{"start": "01:00", "end": "08:00"}],
    )
    assert result == datetime(2026, 8, 14, 17, 0, tzinfo=UTC)


def test_window_validation_rejects_empty_and_overlap() -> None:
    """全天空区间和跨午夜重叠不能进入持久化设置。"""

    with pytest.raises(ValueError, match="不能相同"):
        validate_windows([{"start": "08:00", "end": "08:00"}])
    with pytest.raises(ValueError, match="不能互相重叠"):
        validate_windows(
            [
                {"start": "23:00", "end": "06:00"},
                {"start": "05:00", "end": "07:00"},
            ]
        )
