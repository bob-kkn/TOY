"""
Service/gis_modules/skeleton/generator.py

입력 면형(Polygon)을 병합하고 Voronoi 다이어그램 기반의 원시 뼈대(LineString)를 생성합니다.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, Polygon, MultiPolygon
from shapely.ops import unary_union, voronoi_diagram

from Common.log import Log
from .policy import SkeletonPolicy
from .topology_cluster import TopologyClusterer

class VoronoiGenerator:
    def __init__(self, logger: Log):
        self._logger = logger

    def merge_polygons(self, gdf: gpd.GeoDataFrame, policy: SkeletonPolicy) -> Optional[Any]:
        """거리 + 공유경계 비율 기반으로 면형 그룹을 병합합니다."""
        geoms = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]
        if not geoms:
            return None

        used = [False] * len(geoms)
        merged_parts = []
        distance_th = max(policy.merge_distance_min_m, policy.min_lane_width_m * policy.merge_distance_lane_width_ratio)
        clusterer = TopologyClusterer(geoms, policy, distance_th)

        for i, _ in enumerate(geoms):
            if used[i]:
                continue
            cluster = [i]
            used[i] = True
            changed = True
            while changed:
                changed = False
                for j, _ in enumerate(geoms):
                    if used[j]:
                        continue
                    if clusterer.can_attach(cluster, j):
                        cluster.append(j)
                        used[j] = True
                        changed = True

            merged_parts.append(unary_union([geoms[idx] for idx in cluster]))

        merged = unary_union(merged_parts)
        if hasattr(merged, "is_valid") and not merged.is_valid:
            merged = merged.buffer(0)
        return merged

    def stabilize_geometry(self, geom: Any, policy: SkeletonPolicy) -> Any:
        if geom is None or geom.is_empty:
            return geom

        polys = self._to_polygons(geom)
        stable_polys: List[Polygon] = []
        for poly in polys:
            try:
                cleaned = poly.buffer(-policy.protrusion_clean_m).buffer(policy.protrusion_clean_m)
                cleaned = cleaned.simplify(policy.sharp_angle_simplify_m, preserve_topology=True)
                if not cleaned.is_valid:
                    cleaned = cleaned.buffer(0)
                if cleaned.is_empty:
                    continue

                if self._passes_min_width(cleaned, policy):
                    if isinstance(cleaned, Polygon):
                        stable_polys.append(cleaned)
                    elif isinstance(cleaned, MultiPolygon):
                        stable_polys.extend([p for p in cleaned.geoms if not p.is_empty])
            except Exception as e:
                self._logger.log(f"[Skeleton:Preprocess] 안정화 실패: {e}", level="WARNING")

        if not stable_polys:
            return geom

        out = unary_union(stable_polys)
        if hasattr(out, "is_valid") and not out.is_valid:
            out = out.buffer(0)
        return out

    def generate_voronoi_skeleton(self, geom: Any, policy: SkeletonPolicy) -> List[LineString]:
        polygons = self._to_polygons(geom)
        all_lines: List[LineString] = []

        for poly in polygons:
            if poly.is_empty:
                continue
            try:
                densified = poly.segmentize(policy.voronoi_density_interval_m)
                coords = list(densified.exterior.coords)
                for interior in densified.interiors:
                    coords.extend(list(interior.coords))
                if len(coords) < 3:
                    continue

                vor = voronoi_diagram(MultiPoint(coords))
                ridges = [part.boundary for part in getattr(vor, "geoms", [])]
                merged_ridges = unary_union(ridges)
                skeleton_geom = merged_ridges.intersection(poly)
                if isinstance(skeleton_geom, LineString):
                    all_lines.append(skeleton_geom)
                elif isinstance(skeleton_geom, MultiLineString):
                    all_lines.extend(list(skeleton_geom.geoms))
                elif hasattr(skeleton_geom, "geoms"):
                    all_lines.extend([g for g in skeleton_geom.geoms if isinstance(g, LineString)])
            except Exception as e:
                self._logger.log(f"[Skeleton] Voronoi 생성 실패: {e}", level="WARNING")

        return self._filter_by_min_width(all_lines, geom, policy)

    def generate_boundary_pair_centerlines(self, geom: Any, policy: SkeletonPolicy) -> List[LineString]:
        polygons = self._to_polygons(geom)
        out_lines: List[LineString] = []

        for poly in polygons:
            axis, normal = self._estimate_axes(poly)
            if axis is None or normal is None:
                continue

            sampled = self._sample_boundary_points(poly, policy.pair_sample_step_m, policy)
            if len(sampled) < 4:
                continue

            cx, cy = poly.centroid.x, poly.centroid.y
            buckets = {}
            for x, y in sampled:
                rel_x = x - cx
                rel_y = y - cy
                longitudinal = rel_x * axis[0] + rel_y * axis[1]
                lateral = rel_x * normal[0] + rel_y * normal[1]
                key = round(longitudinal / policy.pair_axis_bin_m)
                side = "L" if lateral >= 0 else "R"
                buckets.setdefault(key, {}).setdefault(side, []).append((x, y, abs(lateral)))

            mids: List[Tuple[float, float, float]] = []
            for key, pairs in buckets.items():
                if "L" not in pairs or "R" not in pairs:
                    continue
                left = max(pairs["L"], key=lambda x: x[2])
                right = max(pairs["R"], key=lambda x: x[2])
                width = math.hypot(left[0] - right[0], left[1] - right[1])
                if width < policy.min_lane_width_m:
                    continue
                mids.append((key, (left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0))

            mids.sort(key=lambda x: x[0])
            segment_pts: List[Tuple[float, float]] = []
            for idx, (_, mx, my) in enumerate(mids):
                if idx > 0:
                    px, py = mids[idx - 1][1], mids[idx - 1][2]
                    if math.hypot(mx - px, my - py) > policy.pair_axis_bin_m * policy.pair_segment_break_bin_ratio and len(segment_pts) >= 2:
                        out_lines.append(LineString(segment_pts))
                        segment_pts = []
                segment_pts.append((mx, my))
            if len(segment_pts) >= 2:
                out_lines.append(LineString(segment_pts))

        return out_lines

    def _to_polygons(self, geom: Any) -> List[Polygon]:
        if isinstance(geom, Polygon):
            return [geom]
        if isinstance(geom, MultiPolygon):
            return list(geom.geoms)
        return []

    def _passes_min_width(self, poly: Any, policy: SkeletonPolicy) -> bool:
        try:
            polygons = self._to_polygons(poly)
            if not polygons:
                return False
            for p in polygons:
                rect = p.minimum_rotated_rectangle
                coords = list(rect.exterior.coords)
                if len(coords) < 5:
                    continue
                lengths = [math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]) for i in range(4)]
                if min(lengths) < policy.min_lane_width_m:
                    return False
            return True
        except Exception:
            return True

    def _filter_by_min_width(self, lines: List[LineString], geom: Any, policy: SkeletonPolicy) -> List[LineString]:
        polygons = self._to_polygons(geom)
        if not polygons:
            return lines
        filtered: List[LineString] = []
        for line in lines:
            if line is None or line.is_empty or line.length <= 0:
                continue
            mid = line.interpolate(0.5, normalized=True)
            if not isinstance(mid, Point):
                continue
            min_width = None
            for poly in polygons:
                if not poly.contains(mid):
                    continue
                width = float(poly.boundary.distance(mid) * 2.0)
                min_width = width if min_width is None else min(min_width, width)
            if min_width is None or min_width >= policy.min_lane_width_m:
                filtered.append(line)
        return filtered

    def _estimate_axes(self, poly: Polygon) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
        try:
            rect = poly.minimum_rotated_rectangle
            coords = list(rect.exterior.coords)
            if len(coords) < 5:
                return None, None
            best = max(
                ((coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]) for i in range(4)),
                key=lambda v: math.hypot(v[0], v[1]),
            )
            ln = math.hypot(best[0], best[1])
            axis = (best[0] / ln, best[1] / ln)
            return axis, (-axis[1], axis[0])
        except Exception:
            return None, None

    def _sample_boundary_points(self, poly: Polygon, step_m: float, policy: SkeletonPolicy) -> List[Tuple[float, float]]:
        length = float(poly.exterior.length)
        if length <= 0:
            return []
        n = max(8, int(length / max(step_m, policy.boundary_sample_min_step_m)))
        return [
            (float(poly.exterior.interpolate((i / n) * length).x), float(poly.exterior.interpolate((i / n) * length).y))
            for i in range(n)
        ]
