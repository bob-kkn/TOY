"""
Service/gis_modules/topology/cleaners.py

위상 네트워크에서 불필요한 잔가지, Y자 갈래, 단순 연결 마디 등을 제거하는 정제 모듈입니다.
"""
from __future__ import annotations

from typing import Optional
import geopandas as gpd
import momepy
import networkx as nx
from shapely.geometry import Point

from Common.log import Log


class SpurCleaner:
    """
    한쪽 끝이 막혀 있는 짧은 잔가지를 줄기 단위로 추적하여 삭제합니다.
    """

    def __init__(self, logger: Log):
        self._logger = logger
        self._precision = 3
        self._max_spur_len = 2.5

    def execute(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf

        graph = nx.MultiGraph()
        for idx, geom in enumerate(gdf.geometry):
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                continue
            u = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            v = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            graph.add_edge(u, v, key=idx, geometry=geom, length=geom.length)

        removed_count = 0
        while True:
            degrees = dict(graph.degree())
            dead_ends = [n for n, d in degrees.items() if d == 1]

            if not dead_ends:
                break

            edges_to_remove = []
            for node in dead_ends:
                path_info = self._trace_spur_path(graph, node)
                if path_info and path_info['total_len'] <= self._max_spur_len:
                    edges_to_remove.extend(path_info['edges'])

            if not edges_to_remove:
                break

            unique_targets = set(edges_to_remove)
            for u, v, k in unique_targets:
                if graph.has_edge(u, v, k):
                    graph.remove_edge(u, v, k)
                    removed_count += 1

            graph.remove_nodes_from(list(nx.isolates(graph)))

        if removed_count == 0:
            return gdf

        final_lines = [data['geometry'] for u, v, k, data in graph.edges(keys=True, data=True)]
        self._logger.log(f"[Topology:SpurCleaner] 일반 잔가지 제거 완료: {removed_count}개 선분 삭제", level="INFO")

        return gpd.GeoDataFrame(geometry=final_lines, crs=gdf.crs)

    def _trace_spur_path(self, graph: nx.MultiGraph, start_node: tuple) -> Optional[dict]:
        """막다른 끝점에서 교차로를 만날 때까지의 경로와 누적 길이를 계산합니다."""
        total_len = 0.0
        edges = []
        visited = {start_node}
        curr = start_node

        while True:
            neighbors = list(graph.neighbors(curr))
            next_nodes = [n for n in neighbors if n not in visited]

            if not next_nodes:
                break

            nxt = next_nodes[0]
            edge_data = graph.get_edge_data(curr, nxt)
            key = list(edge_data.keys())[0]

            total_len += edge_data[key]['length']
            edges.append((curr, nxt, key))

            if graph.degree(nxt) >= 3:
                return {'edges': edges, 'total_len': total_len}

            curr = nxt
            visited.add(curr)

            if graph.degree(curr) == 1:
                break

        return {'edges': edges, 'total_len': total_len}


class TerminalForkCleaner:
    """
    도로 경계선 부근에서 발생하는 Y자형 갈래나 꺾임 잔여물을 지능적으로 제거합니다.
    """
    def __init__(self, logger: Log):
        self._logger = logger
        self._precision = 3
        self._boundary_threshold = 0.8
        self._max_fork_len = 25.0
        self._max_hook_len = 4.0

    def execute(self, gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty or input_gdf.empty:
            return gdf

        merged_poly = input_gdf.geometry.union_all()
        boundary_line = merged_poly.boundary

        graph = nx.MultiGraph()
        for idx, geom in enumerate(gdf.geometry):
            if geom is None or geom.is_empty or len(geom.coords) < 2:
                continue
            u = (round(geom.coords[0][0], self._precision), round(geom.coords[0][1], self._precision))
            v = (round(geom.coords[-1][0], self._precision), round(geom.coords[-1][1], self._precision))
            graph.add_edge(u, v, key=idx, geometry=geom, length=geom.length)

        removed_total = 0
        while True:
            degrees = dict(graph.degree())
            dead_ends = [n for n, d in degrees.items() if d == 1]

            if not dead_ends:
                break

            junction_map = {}
            for node in dead_ends:
                pt = Point(node)
                if pt.distance(boundary_line) <= self._boundary_threshold:
                    path_info = self._trace_to_junction(graph, node)
                    if path_info:
                        j_node = path_info['junction']
                        if j_node not in junction_map:
                            junction_map[j_node] = []
                        junction_map[j_node].append(path_info)

            edges_to_remove = []
            for j_node, paths in junction_map.items():
                if len(paths) >= 2:
                    for p in paths:
                        if p['total_len'] <= self._max_fork_len:
                            edges_to_remove.extend(p['edges'])
                else:
                    p = paths[0]
                    accumulated_len = 0.0
                    hook_edges = []

                    for edge in p['edges']:
                        u, v, k = edge
                        edge_len = graph.get_edge_data(u, v)[k]['length']
                        if not hook_edges and edge_len > self._max_hook_len:
                            break
                        if accumulated_len + edge_len <= self._max_hook_len:
                            hook_edges.append(edge)
                            accumulated_len += edge_len
                        else:
                            break
                    edges_to_remove.extend(hook_edges)

            if not edges_to_remove:
                break

            unique_targets = set(edges_to_remove)
            for u, v, k in unique_targets:
                if graph.has_edge(u, v, k):
                    graph.remove_edge(u, v, k)
                    removed_total += 1

            graph.remove_nodes_from(list(nx.isolates(graph)))

        if removed_total == 0:
            return gdf

        final_lines = [data['geometry'] for u, v, k, data in graph.edges(keys=True, data=True)]
        self._logger.log(f"[Topology:ForkCleaner] 하이브리드 끝단 제거 완료: 총 {removed_total}개 선분 삭제", level="INFO")

        return gpd.GeoDataFrame(geometry=final_lines, crs=gdf.crs)

    def _trace_to_junction(self, graph: nx.MultiGraph, start_node: tuple) -> Optional[dict]:
        """단말 노드에서 가장 가까운 교차로까지의 경로와 마디 정보를 추적합니다."""
        total_len = 0.0
        edges = []
        visited = {start_node}
        curr = start_node

        while True:
            neighbors = list(graph.neighbors(curr))
            next_nodes = [n for n in neighbors if n not in visited]

            if not next_nodes:
                break

            nxt = next_nodes[0]
            edge_data = graph.get_edge_data(curr, nxt)
            key = list(edge_data.keys())[0]

            total_len += edge_data[key]['length']
            edges.append((curr, nxt, key))

            if graph.degree(nxt) >= 3:
                return {'edges': edges, 'total_len': total_len, 'junction': nxt}

            curr = nxt
            visited.add(curr)

            if graph.degree(curr) == 1:
                break

        return {'edges': edges, 'total_len': total_len, 'junction': curr}


class TopologyCleaner:
    """
    네트워크상에서 불필요하게 나뉜 두 개의 선분을 하나의 선분으로 병합합니다.
    """

    def __init__(self, logger: Log):
        self._logger = logger

    def execute(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gdf.empty:
            return gdf
        try:
            cleaned_gdf = momepy.remove_false_nodes(gdf)
            self._logger.log(f"[Topology:Cleaner] False Node 병합 완료: {len(gdf)} -> {len(cleaned_gdf)}", level="INFO")
            return cleaned_gdf
        except Exception as e:
            self._logger.log(f"[Topology:Cleaner] 병합 중 오류 발생: {e}", level="WARNING")
            return gdf