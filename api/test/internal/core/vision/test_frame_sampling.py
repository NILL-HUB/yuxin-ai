"""抽帧策略纯函数测试：帧数随时长对数增长，1 小时触顶 60 帧。"""
import pytest

from internal.core.vision.frame_sampling import (
    L1_MAX_FRAMES,
    L1_MIN_FRAMES,
    plan_frame_offsets,
    resolve_l1_frame_count,
)


class TestResolveL1FrameCount:
    def test_short_video_hits_lower_bound(self):
        """10 秒视频取下限，不会稀疏到 1 帧。"""
        assert resolve_l1_frame_count(10) == L1_MIN_FRAMES

    def test_one_hour_hits_upper_bound(self):
        """1 小时恰好触顶 60 帧。"""
        assert resolve_l1_frame_count(3600) == L1_MAX_FRAMES

    def test_beyond_one_hour_stays_capped(self):
        """超过 1 小时不再增长（封顶）。"""
        assert resolve_l1_frame_count(7200) == L1_MAX_FRAMES
        assert resolve_l1_frame_count(14400) == L1_MAX_FRAMES

    def test_grows_monotonically_with_duration(self):
        durations = [10, 60, 300, 1800, 3600]
        counts = [resolve_l1_frame_count(d) for d in durations]
        assert counts == sorted(counts)

    def test_minute_video_has_more_frames_than_ten_seconds(self):
        assert resolve_l1_frame_count(60) > resolve_l1_frame_count(10)

    def test_zero_or_negative_duration_is_safe(self):
        """异常时长不得崩溃，退回下限。"""
        assert resolve_l1_frame_count(0) == L1_MIN_FRAMES
        assert resolve_l1_frame_count(-5) == L1_MIN_FRAMES


class TestPlanFrameOffsets:
    def test_offsets_are_evenly_spaced(self):
        offsets = plan_frame_offsets(60.0)
        count = resolve_l1_frame_count(60)
        assert len(offsets) == count
        gaps = [round(b - a, 6) for a, b in zip(offsets, offsets[1:])]
        assert len(set(gaps)) == 1, f"间隔应一致，实际 {gaps}"

    def test_first_offset_is_midpoint_of_first_slot(self):
        """首帧取第一个区间的中点，避免永远取到片头黑帧。"""
        offsets = plan_frame_offsets(60.0)
        count = resolve_l1_frame_count(60)
        assert offsets[0] == pytest.approx(60.0 / count / 2, abs=0.01)

    def test_offsets_cover_whole_video_not_only_opening(self):
        """关键回归：最后一帧必须落在视频后段，而非只覆盖开头。"""
        offsets = plan_frame_offsets(3600.0)
        assert offsets[-1] > 3600.0 * 0.9

    def test_offsets_are_within_duration(self):
        for duration in (10.0, 60.0, 3600.0):
            for offset in plan_frame_offsets(duration):
                assert 0 <= offset < duration

    def test_zero_duration_returns_empty(self):
        assert plan_frame_offsets(0) == []
