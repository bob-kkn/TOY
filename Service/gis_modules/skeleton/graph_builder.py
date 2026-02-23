"""
Service/gis_modules/skeleton/graph_builder.py

선형 데이터를 위상 기반의 그래프로 변환하고 정제 후 다시 선형 데이터로 추출하는 빌더 모듈입니다.
"""
from __future__ import annotations

import math
from typing import Any, List, Tuple

import networkx as nx
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

    def separate_parallel_and_reconnect(self, graph: nx.Graph, policy: SkeletonPolicy) -> nx.Graph:
        """평행/근접 엣지 분리 후, 방향 기반 끊김 연결을 수행합니다."""
        graph = self._split_parallel_close_edges(graph, policy)
        graph = self._reconnect_directional_breaks(graph, policy)
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
                tx = node[0] + (ax / an) * 0.5
                ty = node[1] + (ay / an) * 0.5
                nxp = (1 - policy.graph_smooth_alpha) * node[0] + policy.graph_smooth_alpha * tx
                nyp = (1 - policy.graph_smooth_alpha) * node[1] + policy.graph_smooth_alpha * ty
                new_positions[node] = self._round_xy(nxp, nyp)

            remapped = nx.Graph()
            for u, v in graph.edges():
                uu = new_positions.get(u, u)
                vv = new_positions.get(v, v)
                if uu == vv:
                    continue
                geom = self._directional_smooth_and_resample(LineString([uu, vv]), policy)
                if geom is None or geom.is_empty:
                    continue
                remapped.add_edge(uu, vv, weight=float(geom.length), geometry=geom)
            graph = remapped
        return graph

    def export_graph_to_lines(self, graph: nx.Graph) -> List[LineString]:
        return [data["geometry"] for _, _, data in graph.edges(data=True)]

    def _split_parallel_close_edges(self, graph: nx.Graph, policy: SkeletonPolicy) -> nx.Graph:
        edges = list(graph.edges(data=True))
        for i in range(len(edges)):
            u1, v1, d1 = edges[i]
            l1 = d1.get("geometry")
            if l1 is None:
                continue
            mid1 = l1.interpolate(0.5, normalized=True)
            dir1 = self._edge_dir(u1, v1)
            for j in range(i + 1, len(edges)):
                u2, v2, d2 = edges[j]
                l2 = d2.get("geometry")
                if l2 is None:
                    continue
                mid2 = l2.interpolate(0.5, normalized=True)
                if mid1.distance(mid2) > policy.min_lane_width_m * 0.8:
                    continue
                dir2 = self._edge_dir(u2, v2)
                angle = self._angle_between(dir1, dir2)
                if angle > 12.0:
                    continue
                # 살짝 옆으로 밀어 중첩 분리
                if graph.has_edge(u2, v2):
                    offset = policy.min_lane_width_m * 0.2
                    nu = self._round_xy(u2[0] + offset, u2[1] + offset)
                    nv = self._round_xy(v2[0] + offset, v2[1] + offset)
                    graph.remove_edge(u2, v2)
                    graph.add_edge(nu, nv, weight=float(LineString([nu, nv]).length), geometry=LineString([nu, nv]))
        return graph

    def _reconnect_directional_breaks(self, graph: nx.Graph, policy: SkeletonPolicy) -> nx.Graph:
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
                graph.add_edge(a, b, weight=float(geom.length), geometry=geom)
        return graph

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
        step = max(0.4, policy.resample_step_m)
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

    def _round_xy(self, x: float, y: float) -> Tuple[float, float]:
        return round(float(x), COORD_PRECISION), round(float(y), COORD_PRECISION)
