"""
Service/gis_modules/skeleton/policy.py

Skeleton 파이프라인의 임계값/정책 세트를 정의합니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SkeletonPolicy:
    name: str
    protrusion_clean_m: float
    sharp_angle_simplify_m: float
    min_lane_width_m: float
    pair_sample_step_m: float
    pair_axis_bin_m: float
    graph_smooth_iterations: int
    graph_smooth_alpha: float
    reconnect_search_radius_m: float
    reconnect_angle_deg: float
    postprocess_min_len_m: float
    direction_smooth_window: int
    resample_step_m: float

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    @classmethod
    def from_width_distribution(cls, widths: Iterable[float]) -> "SkeletonPolicy":
        vals = sorted([float(w) for w in widths if w and w > 0])
        if not vals:
            vals = [8.0]
        median_w = vals[len(vals) // 2]

        is_rural = median_w >= 12.0
        name = "rural" if is_rural else "urban"

        min_lane_width = cls._clamp(median_w * 0.12, 1.4, 3.5)
        pair_step = cls._clamp(median_w * 0.16, 1.0, 3.0)
        axis_bin = cls._clamp(median_w * 0.10, 0.8, 2.0)
        protrusion = cls._clamp(median_w * 0.02, 0.15, 0.5)
        sharp = cls._clamp(median_w * 0.018, 0.1, 0.45)
        reconnect_r = cls._clamp(median_w * 0.9, 4.0, 14.0)
        post_min_len = cls._clamp(median_w * 0.15, 1.0, 4.0)
        resample_step = cls._clamp(median_w * 0.12, 0.8, 2.5)

        return cls(
            name=name,
            protrusion_clean_m=protrusion,
            sharp_angle_simplify_m=sharp,
            min_lane_width_m=min_lane_width,
            pair_sample_step_m=pair_step,
            pair_axis_bin_m=axis_bin,
            graph_smooth_iterations=3 if is_rural else 2,
            graph_smooth_alpha=0.30 if is_rural else 0.35,
            reconnect_search_radius_m=reconnect_r,
            reconnect_angle_deg=25.0 if is_rural else 20.0,
            postprocess_min_len_m=post_min_len,
            direction_smooth_window=5 if is_rural else 4,
            resample_step_m=resample_step,
        )
