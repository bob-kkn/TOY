"""
Service/gis_modules/skeleton/selector.py

생성된 다중 후보 라인을 점수 기반으로 선별해 그래프 입력 품질을 높입니다.
"""
from __future__ import annotations

import math
from typing import Any, List

from shapely.geometry import LineString

from Common.log import Log
from .policy import SkeletonPolicy


class SkeletonCandidateSelector:
    def __init__(self, logger: Log):
        self._logger = logger

    def select(self, lines: List[LineString], boundary_geom: Any, policy: SkeletonPolicy, group_name: str) -> List[LineString]:
        scored = []
        for line in lines:
            if line is None or line.is_empty or not isinstance(line, LineString) or line.length <= 0:
                continue
            score = self._quality_score(line, boundary_geom, policy)
            scored.append((score, line))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        quality_filtered = [item for item in scored if item[0] >= policy.selector_min_quality_score]
        base_pool = quality_filtered if quality_filtered else scored

        keep_count = max(1, int(math.ceil(len(base_pool) * policy.selector_keep_top_ratio)))
        selected = [line for _, line in base_pool[:keep_count]]

        self._logger.log(
            (
                f"[Skeleton:Selector:{group_name}] "
                f"input={len(lines)}, scored={len(scored)}, "
                f"quality_pass={len(quality_filtered)}, selected={len(selected)}, "
                f"min_quality={policy.selector_min_quality_score:.2f}, top_ratio={policy.selector_keep_top_ratio:.2f}"
            ),
            level="INFO",
        )
        return selected

    def _quality_score(self, line: LineString, boundary_geom: Any, policy: SkeletonPolicy) -> float:
        inside_ratio = self._inside_ratio(line, boundary_geom, policy)
        curvature_penalty = self._curvature_penalty(line)
        length_score = self._length_score(line, policy)

        score = (inside_ratio * 0.55) + ((1.0 - curvature_penalty) * 0.25) + (length_score * 0.20)
        return max(0.0, min(1.0, score))

    def _inside_ratio(self, line: LineString, boundary_geom: Any, policy: SkeletonPolicy) -> float:
        if boundary_geom is None or getattr(boundary_geom, "is_empty", False):
            return 0.0
        step = max(policy.selector_inside_sample_step_m, 0.1)
        sample_n = max(3, int(math.ceil(line.length / step)) + 1)
        hit = 0
        for i in range(sample_n):
            d = (i / (sample_n - 1)) * line.length
            pt = line.interpolate(d)
            if boundary_geom.covers(pt):
                hit += 1
        return hit / float(sample_n)

    def _curvature_penalty(self, line: LineString) -> float:
        coords = list(line.coords)
        if len(coords) < 3:
            return 0.0

        total = 0.0
        turns = 0
        for i in range(1, len(coords) - 1):
            ax = coords[i][0] - coords[i - 1][0]
            ay = coords[i][1] - coords[i - 1][1]
            bx = coords[i + 1][0] - coords[i][0]
            by = coords[i + 1][1] - coords[i][1]

            na = math.hypot(ax, ay)
            nb = math.hypot(bx, by)
            if na == 0 or nb == 0:
                continue

            dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
            total += math.acos(dot)
            turns += 1

        if turns == 0:
            return 0.0
        return max(0.0, min(1.0, total / (math.pi * turns)))

    def _length_score(self, line: LineString, policy: SkeletonPolicy) -> float:
        target = max(policy.min_lane_width_m * policy.selector_length_ref_factor, policy.postprocess_min_len_m)
        if target <= 0:
            return 1.0
        return max(0.0, min(1.0, line.length / target))
