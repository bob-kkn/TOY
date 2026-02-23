"""
Service/gis_modules/topology/strategies.py

중심선의 연결성을 확보하고 교차로 구조를 정규화하여 최종 직선화 결과물을 생성하는 전략 모듈입니다.
"""
from __future__ import annotations

from typing import List, Any, Tuple
import math

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union

from Common.log import Log
from Service.config import GISConfig


class CoordinateSnapper:
    """
    부동 소수점 오차로 인한 좌표 불일치를 해결하기 위해 좌표의 정밀도를 반올림합니다.
    """
    def __init__(self, logger: Log):
        self._logger = logger
        self._precision = 3

    def execute(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf

        out = gdf.copy()
        out["geometry"] = out.geometry.map(self._round_coordinates)

        self._logger.log(f"[Topology:Snapper] 좌표 정밀도 보정 완료 (소수점 {self._precision}자리)", level="INFO")
        return out

    def _round_coordinates(self, geom: Any) -> Any:
        if geom is None or geom.is_empty:
            return geom

        if isinstance(geom, LineString):
            return self._round_line(geom)
        if isinstance(geom, MultiLineString):
            rounded_lines = [self._round_line(ln) for ln in geom.geoms]
            return MultiLineString(rounded_lines)
        return geom

    def _round_line(self, line: LineString) -> LineString:
        """선형 객체의 좌표를 순회하며 중복 점을 제거하고 반올림합니다."""
        rounded_coords = [(round(float(x), self._precision), round(float(y), self._precision)) for x, y in line.coords]
        new_coords = []
        for pt in rounded_coords:
            if not new_coords or new_coords[-1] != pt:
                new_coords.append(pt)
        if len(new_coords) < 2:
            return line
        return LineString(new_coords)


class Planarizer:
    """
    모든 선형 객체가 교차하는 지점에서 물리적으로 분리되도록 평면화 작업을 수행합니다.
    """
    def __init__(self, logger: Log):
        self._logger = logger

    def execute(self, lines: List[LineString], crs: Any) -> gpd.GeoDataFrame:
        if not lines:
            return gpd.GeoDataFrame(columns=["geometry"], crs=crs)

        merged_geom = unary_union(lines)
        planarized_lines = []
        if isinstance(merged_geom, MultiLineString):
            planarized_lines = list(merged_geom.geoms)
        elif isinstance(merged_geom, LineString):
            planarized_lines = [merged_geom]

        valid_lines = [ln for ln in planarized_lines if ln is not None and not ln.is_empty]
        self._logger.log(f"[Topology:Planarizer] 평면화 완료: {len(valid_lines)}개 세그먼트 분할", level="INFO")
        return gpd.GeoDataFrame(geometry=valid_lines, crs=crs)


class IntersectionMerger:
    """
    교차로 사이를 잇는 매우 짧은 선분을 병합하여 복잡한 교차 구조를 단일화합니다.
    """
    def __init__(self, logger: Log, config: GISConfig):
        self._logger = logger
        self._precision = 3
        self._merge_threshold_m = config.topology_intersection_merge_threshold_m
        self._parallel_angle_deg = config.topology_intersection_parallel_angle_deg

    def execute(self, gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf

        graph = nx.MultiGraph()
        for idx, geom in enumerate(gdf.geometry):
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                continue
            u = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            v = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            graph.add_edge(u, v, key=idx, geometry=geom, length=geom.length)

        merged_count = 0
        while True:
            degrees = dict(graph.degree())
            high_deg_nodes = {n for n, d in degrees.items() if d >= 3}

            edge_to_merge = None
            for u, v, key, data in graph.edges(keys=True, data=True):
                if u in high_deg_nodes and v in high_deg_nodes and u != v:
                    if data['length'] <= self._merge_threshold_m:
                        if self._should_preserve_parallel_corridor(graph, u, v, key):
                            continue
                        edge_to_merge = (u, v, key)
                        break

            if not edge_to_merge:
                break

            u, v, key = edge_to_merge
            graph.remove_edge(u, v, key)
            w = (round((u[0]+v[0])/2, self._precision), round((u[1]+v[1])/2, self._precision))

            edges_to_add = []
            edges_to_remove = []
            for node_to_replace in (u, v):
                for neighbor in list(graph.neighbors(node_to_replace)):
                    edge_dict = graph.get_edge_data(node_to_replace, neighbor)
                    for k, edge_data in edge_dict.items():
                        coords = list(edge_data['geometry'].coords)
                        u_start = (round(coords[0][0], self._precision), round(coords[0][1], self._precision))
                        u_end = (round(coords[-1][0], self._precision), round(coords[-1][1], self._precision))

                        if u_start == node_to_replace:
                            coords[0] = w
                        elif u_end == node_to_replace:
                            coords[-1] = w

                        new_geom = LineString(coords)
                        edges_to_remove.append((node_to_replace, neighbor, k))
                        edges_to_add.append((w, neighbor, {'geometry': new_geom, 'length': new_geom.length}))

            for rm_u, rm_v, rm_k in edges_to_remove:
                if graph.has_edge(rm_u, rm_v, rm_k):
                    graph.remove_edge(rm_u, rm_v, rm_k)
            if graph.has_node(u):
                graph.remove_node(u)
            if graph.has_node(v):
                graph.remove_node(v)
            for add_u, add_v, add_data in edges_to_add:
                if add_u != add_v:
                    graph.add_edge(add_u, add_v, **add_data)
            merged_count += 1

        if merged_count == 0:
            return gdf
        final_lines = [data['geometry'] for _, _, _, data in graph.edges(keys=True, data=True)]
        self._logger.log(f"[Topology:Merger] 교차로 다리 병합 완료: {merged_count}개 수축됨", level="INFO")
        return gpd.GeoDataFrame(geometry=final_lines, crs=gdf.crs)

    def _should_preserve_parallel_corridor(self, graph: nx.MultiGraph, u: Tuple[float, float], v: Tuple[float, float], key: int) -> bool:
        """브리지 양쪽 노드에 평행 진행선이 존재하면 병합을 보류합니다."""
        u_dirs = self._collect_neighbor_directions(graph, u, excluded=(u, v, key))
        v_dirs = self._collect_neighbor_directions(graph, v, excluded=(u, v, key))
        if not u_dirs or not v_dirs:
            return False

        for ux, uy in u_dirs:
            for vx, vy in v_dirs:
                dot = max(-1.0, min(1.0, ux * vx + uy * vy))
                angle = math.degrees(math.acos(abs(dot)))
                if angle <= self._parallel_angle_deg:
                    return True
        return False

    def _collect_neighbor_directions(
            self,
            graph: nx.MultiGraph,
            node: Tuple[float, float],
            excluded: Tuple[Tuple[float, float], Tuple[float, float], int]
    ) -> List[Tuple[float, float]]:
        directions: List[Tuple[float, float]] = []
        for neighbor in list(graph.neighbors(node)):
            edge_dict = graph.get_edge_data(node, neighbor) or {}
            for edge_key, edge_data in edge_dict.items():
                if (node == excluded[0] and neighbor == excluded[1] and edge_key == excluded[2]) or (
                    node == excluded[1] and neighbor == excluded[0] and edge_key == excluded[2]
                ):
                    continue

                geom = edge_data.get("geometry")
                if geom is None or geom.is_empty or len(geom.coords) < 2:
                    continue

                coords = list(geom.coords)
                start = (round(coords[0][0], self._precision), round(coords[0][1], self._precision))
                end = (round(coords[-1][0], self._precision), round(coords[-1][1], self._precision))
                if start == node:
                    ref = coords[1]
                elif end == node:
                    ref = coords[-2]
                else:
                    continue

                vx = float(ref[0] - node[0])
                vy = float(ref[1] - node[1])
                norm = math.hypot(vx, vy)
                if norm == 0.0:
                    continue
                directions.append((vx / norm, vy / norm))
        return directions



class IntersectionSmoother:
    """
    교차로 중심점 부근의 불필요한 굴곡 포인트들을 제거하여 진입 선형을 직선화합니다.
    """
    def __init__(self, logger: Log):
        self._logger = logger
        self._precision = 3
        self._clearance_radius_m = 2.0

    def execute(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf

        graph = nx.MultiGraph()
        for idx, geom in enumerate(gdf.geometry):
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                continue
            u = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            v = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            graph.add_edge(u, v, key=idx, geometry=geom)

        degrees = dict(graph.degree())
        high_deg_nodes = {n for n, d in degrees.items() if d >= 3}
        if not high_deg_nodes:
            return gdf

        smoothed_lines = []
        smoothed_count = 0
        for u, v, key, data in graph.edges(keys=True, data=True):
            geom = data['geometry']
            coords = list(geom.coords)
            is_u_junction, is_v_junction = u in high_deg_nodes, v in high_deg_nodes

            if not is_u_junction and not is_v_junction:
                smoothed_lines.append(geom)
                continue

            new_coords = []
            for i, pt in enumerate(coords):
                if i == 0 or i == len(coords) - 1:
                    new_coords.append(pt)
                    continue
                drop = False
                if is_u_junction and (((pt[0]-u[0])**2 + (pt[1]-u[1])**2)**0.5 <= self._clearance_radius_m):
                    drop = True
                if not drop and is_v_junction and (((pt[0]-v[0])**2 + (pt[1]-v[1])**2)**0.5 <= self._clearance_radius_m):
                    drop = True
                if not drop:
                    new_coords.append(pt)

            if len(new_coords) < 2:
                new_coords = [coords[0], coords[-1]]
            new_geom = LineString(new_coords)
            if len(coords) != len(new_coords):
                smoothed_count += 1
            smoothed_lines.append(new_geom)

        self._logger.log(f"[Topology:Smoother] 교차로 평탄화 완료: {smoothed_count}개 간선 직선화", level="INFO")
        return gpd.GeoDataFrame(geometry=smoothed_lines, crs=gdf.crs)


class NetworkSimplifier:
    """
    위상 구조를 보존하면서 선형의 미세한 굴곡을 제거하여 최종 중심선을 단순화합니다.
    """
    def __init__(self, logger: Log, config: GISConfig):
        self._logger = logger
        self._main_tolerance = config.topology_simplify_main_tolerance_m
        self._junction_tolerance = config.topology_simplify_junction_tolerance_m
        self._junction_min_degree = config.topology_junction_min_degree
        self._precision = 3

    def execute(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf

        degree_map = {}
        for geom in gdf.geometry:
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                continue
            s = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            e = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            degree_map[s] = degree_map.get(s, 0) + 1
            degree_map[e] = degree_map.get(e, 0) + 1

        simplified_geoms = []
        junction_edges = 0
        for geom in gdf.geometry:
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                simplified_geoms.append(geom)
                continue
            s = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            e = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            is_junction_edge = degree_map.get(s, 0) >= self._junction_min_degree or degree_map.get(e, 0) >= self._junction_min_degree
            tol = self._junction_tolerance if is_junction_edge else self._main_tolerance
            if is_junction_edge:
                junction_edges += 1
            simplified_geoms.append(geom.simplify(tol, preserve_topology=True))

        out = gpd.GeoDataFrame(gdf.drop(columns="geometry", errors="ignore"), geometry=simplified_geoms, crs=gdf.crs)
        self._logger.log(
            "[Topology:Simplifier] 위상 보존 단순화 완료 "
            f"(Main={self._main_tolerance}m, Junction={self._junction_tolerance}m, JunctionEdges={junction_edges})",
            level="INFO",
        )
        return out
