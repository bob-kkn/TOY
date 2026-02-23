"""
Service/gis_modules/skeleton/graph_builder.py

선형 데이터를 위상 기반의 그래프로 변환하고 정제 후 다시 선형 데이터로 추출하는 빌더 모듈입니다.
"""
from __future__ import annotations

import math
from typing import Any, List, Tuple

import networkx as nx
from shapely import affinity
from shapely.geometry import LineString, Point
from shapely.ops import linemerge

from Common.log import Log
from .policy import SkeletonPolicy

COORD_PRECISION = 3
MIN_RADIUS = 0.1


class SkeletonGraphBuilder:
    def __init__(self, logger: Log):
        self._logger = logger

    def build_context_aware_graph(self, lines: List[LineString], boundary_geom: Any) -> nx.Graph:
        graph = nx.Graph()
        graph.graph["boundary_geom"] = boundary_geom
        boundary_line = boundary_geom.boundary
        for line in lines:
            if line is None or line.is_empty:
                continue
            start = self._round_xy(*line.coords[0])
            end = self._round_xy(*line.coords[-1])
            if start == end:
                continue
            graph.add_edge(start, end, weight=float(line.length), geometry=line)
            for node in (start, end):
                if "radius" not in graph.nodes[node]:
                    graph.nodes[node]["radius"] = max(float(boundary_line.distance(Point(node))), MIN_RADIUS)
        return graph

    def merge_degree_2_nodes(self, graph: nx.Graph) -> nx.Graph:
        while True:
            nodes = [n for n, d in graph.degree() if d == 2]
            if not nodes:
                break
            merged_count = 0
            for node in nodes:
                if not graph.has_node(node):
                    continue
                neighbors = list(graph.neighbors(node))
                if len(neighbors) != 2:
                    continue
                u, v = neighbors
                e1 = graph.get_edge_data(u, node)
                e2 = graph.get_edge_data(node, v)
                if not e1 or not e2:
                    continue
                try:
                    merged = linemerge([e1["geometry"], e2["geometry"]])
                    if not isinstance(merged, LineString):
                        continue
                    graph.remove_node(node)
                    graph.add_edge(u, v, weight=float(merged.length), geometry=merged)
                    merged_count += 1
                except Exception:
                    continue
            if merged_count == 0:
                break
        return graph

    def separate_parallel_and_reconnect(self, graph: nx.Graph, policy: SkeletonPolicy, boundary_geom: Any) -> nx.Graph:
        """평행/근접 엣지 분리 후, 방향 기반 끊김 연결을 수행합니다."""
        graph = self._split_parallel_close_edges(graph, policy)
        graph = self._reconnect_directional_breaks(graph, policy, boundary_geom)
        return graph

    def smooth_by_direction_field(self, graph: nx.Graph, policy: SkeletonPolicy) -> nx.Graph:
        if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
            return graph
        for _ in range(max(1, policy.graph_smooth_iterations)):
            new_positions = {}
            for node in graph.nodes():
                neighbors = list(graph.neighbors(node))
                if len(neighbors) < 2:
                    continue
                vecs = []
                for nb in neighbors:
                    dx, dy = nb[0] - node[0], nb[1] - node[1]
                    ln = math.hypot(dx, dy)
                    if ln > 0:
                        vecs.append((dx / ln, dy / ln))
                if len(vecs) < 2:
                    continue
                ax = sum(v[0] for v in vecs) / len(vecs)
                ay = sum(v[1] for v in vecs) / len(vecs)
                an = math.hypot(ax, ay)
                if an == 0:
                    continue
                tx = node[0] + (ax / an) * policy.graph_smooth_target_shift_m
                ty = node[1] + (ay / an) * policy.graph_smooth_target_shift_m
                nxp = (1 - policy.graph_smooth_alpha) * node[0] + policy.graph_smooth_alpha * tx
                nyp = (1 - policy.graph_smooth_alpha) * node[1] + policy.graph_smooth_alpha * ty
                new_positions[node] = self._round_xy(nxp, nyp)

            remapped = nx.Graph()
            for u, v, data in graph.edges(data=True):
                uu = new_positions.get(u, u)
                vv = new_positions.get(v, v)
                if uu == vv:
                    continue

                base_geom = data.get("geometry")
                if base_geom is None or base_geom.is_empty or len(base_geom.coords) < 2:
                    continue

                morphed = self._morph_geometry_with_new_endpoints(base_geom, u, v, uu, vv)
                geom = self._directional_smooth_and_resample(morphed, policy)
                if geom is None or geom.is_empty:
                    continue
                remapped.add_edge(uu, vv, weight=float(geom.length), geometry=geom)
            graph = remapped
        return graph

    def export_graph_to_lines(self, graph: nx.Graph) -> List[LineString]:
        return [data["geometry"] for _, _, data in graph.edges(data=True)]

    def _split_parallel_close_edges(self, graph: nx.Graph, policy: SkeletonPolicy) -> nx.Graph:
        edges = list(graph.edges(data=True))
        moved_edges: set[tuple[Tuple[float, float], Tuple[float, float]]] = set()

        for i in range(len(edges)):
            u1, v1, d1 = edges[i]
            l1 = d1.get("geometry")
            if l1 is None or l1.is_empty:
                continue
            dir1 = self._edge_dir(u1, v1)

            for j in range(i + 1, len(edges)):
                u2, v2, d2 = edges[j]
                l2 = d2.get("geometry")
                if l2 is None or l2.is_empty:
                    continue

                key2 = (u2, v2) if u2 <= v2 else (v2, u2)
                if key2 in moved_edges:
                    continue

                min_dist = l1.distance(l2)
                if min_dist > policy.min_lane_width_m * policy.parallel_close_dist_factor:
                    continue

                dir2 = self._edge_dir(u2, v2)
                angle = self._angle_between(dir1, dir2)
                if angle > policy.parallel_angle_deg:
                    continue

                if not graph.has_edge(u2, v2):
                    continue

                offset_m = policy.min_lane_width_m * policy.parallel_offset_factor
                nxv, nyv = self._normal_from_direction(dir2)
                shifted = affinity.translate(l2, xoff=nxv * offset_m, yoff=nyv * offset_m)
                if shifted is None or shifted.is_empty:
                    continue
                shifted = self._round_line(shifted)
                if shifted is None or shifted.is_empty or len(shifted.coords) < 2:
                    continue

                start = self._round_xy(*shifted.coords[0])
                end = self._round_xy(*shifted.coords[-1])
                if start == end:
                    continue

                graph.remove_edge(u2, v2)
                graph.add_edge(start, end, weight=float(shifted.length), geometry=shifted)
                moved_edges.add(key2)
        return graph

    def _reconnect_directional_breaks(self, graph: nx.Graph, policy: SkeletonPolicy, boundary_geom: Any) -> nx.Graph:
        boundary = graph.graph.get("boundary_geom", boundary_geom)
        if boundary is None or getattr(boundary, "is_empty", False):
            return graph
        endpoints = [n for n, d in graph.degree() if d == 1]
        for i, a in enumerate(endpoints):
            for b in endpoints[i + 1 :]:
                dist = math.hypot(a[0] - b[0], a[1] - b[1])
                if dist > policy.reconnect_search_radius_m:
                    continue
                da = self._endpoint_heading(graph, a)
                db = self._endpoint_heading(graph, b)
                if da is None or db is None:
                    continue
                if self._angle_between(da, db) > policy.reconnect_angle_deg:
                    continue
                if graph.has_edge(a, b):
                    continue
                geom = LineString([a, b])
                if geom.length <= 0:
                    continue
                boundary_hit = geom.intersection(boundary)
                inside_ratio = float(boundary_hit.length / geom.length) if geom.length > 0 else 0.0
                if inside_ratio < policy.reconnect_min_inside_ratio:
                    continue
                if not geom.within(boundary.buffer(policy.reconnect_boundary_buffer_m)):
                    continue
                graph.add_edge(a, b, weight=float(geom.length), geometry=geom)
        return graph

    def _morph_geometry_with_new_endpoints(
        self,
        base: LineString,
        old_u: Tuple[float, float],
        old_v: Tuple[float, float],
        new_u: Tuple[float, float],
        new_v: Tuple[float, float],
    ) -> LineString:
        coords = list(base.coords)
        if len(coords) < 2:
            return LineString([new_u, new_v])

        start = self._round_xy(*coords[0])
        end = self._round_xy(*coords[-1])
        if start == old_u and end == old_v:
            coords[0] = new_u
            coords[-1] = new_v
        elif start == old_v and end == old_u:
            coords[0] = new_v
            coords[-1] = new_u
        else:
            coords[0] = new_u
            coords[-1] = new_v

        return LineString(coords)

    def _directional_smooth_and_resample(self, line: LineString, policy: SkeletonPolicy) -> LineString:
        coords = list(line.coords)
        if len(coords) < 2:
            return line

        window = max(3, policy.direction_smooth_window)
        smoothed = []
        for i in range(len(coords)):
            lo = max(0, i - window // 2)
            hi = min(len(coords), i + window // 2 + 1)
            xs = [coords[k][0] for k in range(lo, hi)]
            ys = [coords[k][1] for k in range(lo, hi)]
            smoothed.append((sum(xs) / len(xs), sum(ys) / len(ys)))

        smooth_line = LineString(smoothed)
        if smooth_line.length <= 0:
            return smooth_line
        step = max(policy.resample_min_step_m, policy.resample_step_m)
        n = max(2, int(smooth_line.length / step) + 1)
        pts = [smooth_line.interpolate((i / (n - 1)) * smooth_line.length) for i in range(n)]
        return LineString([(p.x, p.y) for p in pts])

    def _endpoint_heading(self, graph: nx.Graph, node: Tuple[float, float]):
        neighbors = list(graph.neighbors(node))
        if not neighbors:
            return None
        nb = neighbors[0]
        dx = node[0] - nb[0]
        dy = node[1] - nb[1]
        ln = math.hypot(dx, dy)
        if ln == 0:
            return None
        return dx / ln, dy / ln

    def _edge_dir(self, u: Tuple[float, float], v: Tuple[float, float]) -> Tuple[float, float]:
        dx = v[0] - u[0]
        dy = v[1] - u[1]
        ln = math.hypot(dx, dy)
        if ln == 0:
            return 0.0, 0.0
        return dx / ln, dy / ln

    def _angle_between(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
        return math.degrees(math.acos(abs(dot)))

    def _normal_from_direction(self, direction: Tuple[float, float]) -> Tuple[float, float]:
        nxv = -direction[1]
        nyv = direction[0]
        norm = math.hypot(nxv, nyv)
        if norm == 0.0:
            return 0.0, 0.0
        return nxv / norm, nyv / norm

    def _round_line(self, line: LineString) -> LineString:
        rounded = [(round(float(x), COORD_PRECISION), round(float(y), COORD_PRECISION)) for x, y in line.coords]
        dedup = []
        for pt in rounded:
            if not dedup or dedup[-1] != pt:
                dedup.append(pt)
        if len(dedup) < 2:
            return line
        return LineString(dedup)

    def _round_xy(self, x: float, y: float) -> Tuple[float, float]:
        return round(float(x), COORD_PRECISION), round(float(y), COORD_PRECISION)
