"""
Service/gis_modules/skeleton/graph_builder.py

선형 데이터를 위상 기반의 그래프로 변환하고 정제 후 다시 선형 데이터로 추출하는 빌더 모듈입니다.
"""
from __future__ import annotations

from typing import Any, List, Tuple

import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import linemerge

from Common.log import Log

COORD_PRECISION = 3
MIN_RADIUS = 0.1


class SkeletonGraphBuilder:
    """
    중심선 추출 데이터를 위상 그래프로 구축하고 단순 연결 노드를 병합하는 기능을 수행합니다.
    """

    def __init__(self, logger: Log):
        self._logger = logger

    def build_context_aware_graph(self, lines: List[LineString], boundary_geom: Any) -> nx.Graph:
        """
        추출된 선분들을 그래프로 변환하며 각 노드와 면형 경계선 사이의 거리를 계산하여 저장합니다.

        Args:
            lines (List[LineString]): 추출된 중심선 리스트
            boundary_geom (Any): 원본 면형 geometry

        Returns:
            nx.Graph: 노드별 경계 거리가 포함된 위상 그래프
        """
        graph = nx.Graph()
        boundary_line = boundary_geom.boundary

        for line in lines:
            if line is None or line.is_empty:
                continue
            start = self._round_xy(line.coords[0][0], line.coords[0][1])
            end = self._round_xy(line.coords[-1][0], line.coords[-1][1])

            if start == end:
                continue

            length = float(line.length)
            graph.add_edge(start, end, weight=length, geometry=line)

            for node in (start, end):
                if "radius" not in graph.nodes[node]:
                    dist = float(boundary_line.distance(Point(node)))
                    graph.nodes[node]["radius"] = max(dist, MIN_RADIUS)

        return graph

    def merge_degree_2_nodes(self, graph: nx.Graph) -> nx.Graph:
        """
        그래프 내에서 두 개의 간선만 연결된 단순 통과 노드들을 제거하고 선분을 병합합니다.

        Args:
            graph (nx.Graph): 병합 대상 위상 그래프

        Returns:
            nx.Graph: 노드 병합이 완료된 그래프
        """
        while True:
            nodes_to_merge = [n for n, d in graph.degree() if d == 2]
            if not nodes_to_merge:
                break

            merged_count = 0
            for node in nodes_to_merge:
                if not graph.has_node(node):
                    continue
                neighbors = list(graph.neighbors(node))
                if len(neighbors) != 2:
                    continue

                u, v = neighbors[0], neighbors[1]
                edge_u = graph.get_edge_data(u, node)
                edge_v = graph.get_edge_data(node, v)
                if not edge_u or not edge_v:
                    continue

                line1 = edge_u["geometry"]
                line2 = edge_v["geometry"]

                try:
                    merged_geom = linemerge([line1, line2])
                    if not isinstance(merged_geom, LineString):
                        continue
                    new_weight = float(edge_u["weight"]) + float(edge_v["weight"])
                    graph.remove_node(node)
                    graph.add_edge(u, v, weight=new_weight, geometry=merged_geom)
                    merged_count += 1
                except Exception:
                    continue

            if merged_count == 0:
                break

        return graph

    def export_graph_to_lines(self, graph: nx.Graph) -> List[LineString]:
        """
        최종 정제된 그래프의 엣지 정보를 바탕으로 LineString 리스트를 생성합니다.

        Returns:
            List[LineString]: 그래프에서 추출된 선형 데이터 리스트
        """
        return [data["geometry"] for _, _, data in graph.edges(data=True)]

    def _round_xy(self, x: float, y: float) -> Tuple[float, float]:
        """좌표의 정밀도를 반올림하여 위상 연결 시의 오차를 보정합니다."""
        return (round(float(x), COORD_PRECISION), round(float(y), COORD_PRECISION))