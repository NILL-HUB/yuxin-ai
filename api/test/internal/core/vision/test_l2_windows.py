"""L2 区间窗口推导测试（纯函数，无 IO）。

L2 不重扫全片：由 L1 命中帧的 time_offset 推出「要密抽的时间窗口」，
从而把 1 小时视频改 20 秒片段的视觉调用从 7200 次降到约 40 次。
"""
import pytest

from internal.core.vision.frame_sampling import (
    L2_MAX_FRAMES_PER_WINDOW,
    L2_WINDOW_PADDING_SEC,
    merge_time_windows,
    plan_l2_windows,
    resolve_l2_window_frame_count,
)


class TestResolveL2WindowFrameCount:
    def test_half_second_per_frame(self):
        """窗口内每 0.5 秒 1 帧。"""
        assert resolve_l2_window_frame_count(10.0) == 20

    def test_one_second_window(self):
        assert resolve_l2_window_frame_count(1.0) == 2

    def test_at_least_one_frame(self):
        """极短窗口也要产出至少 1 帧，不能退化为 0。"""
        assert resolve_l2_window_frame_count(0.1) == 1

    def test_capped_at_max_frames(self):
        """超长窗口被 600 帧上限截断（= 5 分钟 @0.5s/帧）。"""
        assert resolve_l2_window_frame_count(3600.0) == L2_MAX_FRAMES_PER_WINDOW

    def test_invalid_duration_falls_back_to_one(self):
        assert resolve_l2_window_frame_count(0.0) == 1
        assert resolve_l2_window_frame_count(-3.0) == 1
        assert resolve_l2_window_frame_count("bad") == 1


class TestMergeTimeWindows:
    def test_merges_overlapping_windows(self):
        assert merge_time_windows([(10.0, 20.0), (18.0, 30.0)]) == [(10.0, 30.0)]

    def test_keeps_disjoint_windows_separate(self):
        assert merge_time_windows([(10.0, 20.0), (50.0, 60.0)]) == [(10.0, 20.0), (50.0, 60.0)]

    def test_merges_touching_windows(self):
        """首尾相接（end == next.start）视为同一窗口，避免碎片化。"""
        assert merge_time_windows([(10.0, 20.0), (20.0, 30.0)]) == [(10.0, 30.0)]

    def test_sorts_before_merging(self):
        assert merge_time_windows([(50.0, 60.0), (10.0, 20.0)]) == [(10.0, 20.0), (50.0, 60.0)]

    def test_empty_input(self):
        assert merge_time_windows([]) == []

    def test_swapped_bounds_are_normalized(self):
        """传入 (end, start) 颠倒时按升序归一，不产生负长度窗口。"""
        assert merge_time_windows([(20.0, 10.0)]) == [(10.0, 20.0)]


class TestPlanL2Windows:
    def test_hit_offset_expands_by_padding(self):
        """单个命中时刻向两侧各留白 L2_WINDOW_PADDING_SEC。"""
        windows = plan_l2_windows([100.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_clamps_to_video_bounds(self):
        """窗口不得越过视频首尾（0 ~ duration）。"""
        assert plan_l2_windows([2.0], duration_sec=60.0) == [(0.0, 2.0 + L2_WINDOW_PADDING_SEC)]
        assert plan_l2_windows([59.0], duration_sec=60.0) == [(59.0 - L2_WINDOW_PADDING_SEC, 60.0)]

    def test_merges_nearby_hits(self):
        """相邻命中（扩窗后重叠）合并成一个窗口，避免重复抽帧。"""
        windows = plan_l2_windows([100.0, 105.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 105.0 + L2_WINDOW_PADDING_SEC)]

    def test_multiple_disjoint_hits(self):
        windows = plan_l2_windows([50.0, 300.0], duration_sec=600.0)

        assert windows == [
            (50.0 - L2_WINDOW_PADDING_SEC, 50.0 + L2_WINDOW_PADDING_SEC),
            (300.0 - L2_WINDOW_PADDING_SEC, 300.0 + L2_WINDOW_PADDING_SEC),
        ]

    def test_no_hits_yields_no_windows(self):
        """没有命中就不该抽任何帧（L2 是按需，不是全片重扫）。"""
        assert plan_l2_windows([], duration_sec=600.0) == []

    def test_unknown_duration_does_not_clamp_upper_bound(self):
        """时长未知（<=0）时只做下界保护，不把窗口截成空。"""
        windows = plan_l2_windows([100.0], duration_sec=0.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_explicit_range_overrides_hits(self):
        """显式区间优先于命中推导（规格 §2「A+B」）。"""
        windows = plan_l2_windows(
            [100.0], duration_sec=600.0, explicit_range=(200.0, 260.0)
        )

        assert windows == [(200.0, 260.0)]

    def test_explicit_range_clamped_and_ordered(self):
        windows = plan_l2_windows(
            [], duration_sec=600.0, explicit_range=(700.0, -5.0)
        )

        assert windows == [(0.0, 600.0)]

    def test_invalid_offsets_ignored(self):
        """非数值/负偏移不参与推导，避免污染窗口。"""
        windows = plan_l2_windows([-5.0, "bad", 100.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_merging_can_cover_many_hits(self):
        """一串密集命中最终只产生一个窗口（这就是成本降低的来源）。"""
        hits = [100.0, 102.0, 104.0, 106.0]

        assert len(plan_l2_windows(hits, duration_sec=600.0)) == 1
