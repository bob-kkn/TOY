"""
Service/gis_modules/skeleton/topology_cluster.py

면형 간 위상 관계(공유 경계, 방향 유사도, 거리)를 기반으로
"같은 도로 단위" 클러스터를 결정하는 보조 모듈입니다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from shapely.geometry import Polygon

from .policy import SkeletonPolicy


@dataclass(frozen=True)
class EdgeFeature:
    distance: float
    shared_ratio: float
    axis_similarity: float
    score: float


class TopologyClusterer:
    def __init__(self, geoms: Sequence[Polygon], policy: SkeletonPolicy, distance_th: float):
        self._geoms = list(geoms)
        self._policy = policy
        self._distance_th = max(1e-6, float(distance_th))
        self._axes = [self._long_axis(g) for g in self._geoms]
        self._graph = self._build_graph()

    def can_attach(self, cluster: Sequence[int], cand_idx: int) -> bool:
        """현재 클러스터에 cand_idx를 편입 가능한지 판단합니다."""
        if not cluster:
            return True

        best: Optional[EdgeFeature] = None
        for idx in cluster:
            key = self._pair_key(idx, cand_idx)
            feat = self._graph.get(key)
            if feat is None:
                continue
            if best is None or feat.score > best.score:
                best = feat

        if best is None:
            return False

        shared_hi = self._policy.merge_shared_ratio_th
        shared_lo = shared_hi * 0.5
        axis_hi = 0.75
        axis_mid = 0.55

        if best.distance <= self._distance_th and best.shared_ratio < shared_lo and best.axis_similarity < axis_mid:
            return False

        if best.shared_ratio >= shared_hi and best.axis_similarity >= axis_mid:
            return True

        if (
            best.shared_ratio >= shared_lo
            and best.axis_similarity >= axis_hi
            and best.distance <= self._distance_th
        ):
            return True

        return best.score >= 1.8

    def _build_graph(self) -> Dict[Tuple[int, int], EdgeFeature]:
        graph: Dict[Tuple[int, int], EdgeFeature] = {}
        for i in range(len(self._geoms)):
            gi = self._geoms[i]
            for j in range(i + 1, len(self._geoms)):
                gj = self._geoms[j]
                distance = float(gi.distance(gj))
                shared_len = float(gi.boundary.intersection(gj.boundary).length)
                perim = max(1.0, float(min(gi.length, gj.length)))
                shared_ratio = shared_len / perim
                axis_similarity = self._axis_similarity(self._axes[i], self._axes[j])
                score = self._score(distance, shared_ratio, axis_similarity)
                graph[(i, j)] = EdgeFeature(
                    distance=distance,
                    shared_ratio=shared_ratio,
                    axis_similarity=axis_similarity,
                    score=score,
                )
        return graph

    def _score(self, distance: float, shared_ratio: float, axis_similarity: float) -> float:
        shared_hi = max(1e-6, self._policy.merge_shared_ratio_th)
        shared_lo = shared_hi * 0.5
        near_score = max(0.0, 1.0 - (distance / self._distance_th))

        score = (shared_ratio / shared_hi) * 1.2 + axis_similarity * 0.9 + near_score * 0.3

        if distance <= self._distance_th and shared_ratio < shared_lo and axis_similarity < 0.55:
            score -= 2.0

        return score

    @staticmethod
    def _pair_key(a: int, b: int) -> Tuple[int, int]:
        return (a, b) if a < b else (b, a)

    @staticmethod
    def _axis_similarity(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> float:
        if a is None or b is None:
            return 0.5
        return abs(a[0] * b[0] + a[1] * b[1])

    @staticmethod
    def _long_axis(poly: Polygon) -> Optional[Tuple[float, float]]:
        try:
            rect = poly.minimum_rotated_rectangle
            coords = list(rect.exterior.coords)
            if len(coords) < 5:
                return None
            best = max(
                ((coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]) for i in range(4)),
                key=lambda v: math.hypot(v[0], v[1]),
            )
            ln = math.hypot(best[0], best[1])
            if ln <= 0:
                return None
            return (best[0] / ln, best[1] / ln)
        except Exception:
            return None
