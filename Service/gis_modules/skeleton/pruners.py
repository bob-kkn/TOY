"""
Service/gis_modules/skeleton/pruners.py

중심선 생성 과정에서 발생하는 잔가지, 경계 근접 노이즈 등을 제거하는 정제 전략 모듈입니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import networkx as nx

from Common.log import Log

PRUNE_RATIO_LIMIT = 1.6
MIN_RADIUS = 0.1


@dataclass(frozen=True)
class _EdgePath:
    """단말 노드에서 교차점까지의 경로 정보를 담는 데이터 클래스입니다."""
    nodes: List[Tuple[float, float]]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]]
    total_length: float
    junction_node: Tuple[float, float]
    junction_radius: float

@dataclass(frozen=True)
class _BoundaryNearPolicy:
    """경계선 근접 정제 전략을 위한 임계값 설정입니다."""
    min_radius_hit_m: float = 0.20
    max_hit_ratio: float = 0.30
    max_abs_hits: int = 3
    remove_leaf_edges_count: int = 2
    protect_component_min_total_len_m: float = 30.0
    protect_component_max_radius_m: float = 1.0
    hard_min_radius_m: float = 0.05

@dataclass(frozen=True)
class _ComponentPolicy:
    """독립된 네트워크 파편 제거를 위한 설정입니다."""
    min_component_total_len_m: float = 15.0
    protect_component_max_radius_m: float = 1.0

@dataclass(frozen=True)
class _SpurPolicy:
    """교차로 잔가지 제거를 위한 설정입니다."""
    abs_spur_max_len_m: float = 3.0
    rel_spur_ratio: float = 0.20


def _trace_leaf_to_junction(graph: nx.Graph, leaf: Tuple[float, float]) -> Optional[_EdgePath]:
    """단말 노드에서 시작하여 다른 선로와 만나는 첫 번째 교차점까지의 경로를 추적합니다."""
    current = leaf
    visited = {current}

    nodes = [current]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    total_length = 0.0

    while True:
        neighbors = list(graph.neighbors(current))
        next_candidates = [n for n in neighbors if n not in visited]

        if not next_candidates:
            junction_node = current
            junction_radius = float(graph.nodes[current].get("radius", MIN_RADIUS))
            return _EdgePath(nodes=nodes, edges=edges, total_length=total_length, junction_node=junction_node, junction_radius=junction_radius)

        nxt = next_candidates[0]
        total_length += float(graph.edges[current, nxt].get("weight", 0.0))
        edges.append((current, nxt))

        current = nxt
        visited.add(current)
        nodes.append(current)

        if graph.degree(current) >= 3:
            junction_node = current
            junction_radius = float(graph.nodes[current].get("radius", MIN_RADIUS))
            return _EdgePath(nodes=nodes, edges=edges, total_length=total_length, junction_node=junction_node, junction_radius=junction_radius)


class RatioPruner:
    """도로 폭 대비 선분의 길이를 비교하여 상대적으로 짧은 잔가지를 제거합니다."""
    def __init__(self, logger: Log):
        self._logger = logger

    def execute(self, graph: nx.Graph) -> nx.Graph:
        removed_paths = 0
        removed_edges_total = 0

        while True:
            leaf_nodes = [n for n, d in graph.degree() if d == 1]
            if not leaf_nodes:
                break

            edges_to_remove: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
            processed = False

            for leaf in leaf_nodes:
                path = _trace_leaf_to_junction(graph, leaf)
                if path is None:
                    continue
                threshold_len = path.junction_radius * PRUNE_RATIO_LIMIT
                if path.total_length < threshold_len:
                    edges_to_remove.extend(path.edges)
                    processed = True
                    removed_paths += 1

            if not processed or not edges_to_remove:
                break

            unique_edges = set()
            for u, v in edges_to_remove:
                unique_edges.add((u, v) if u <= v else (v, u))

            graph.remove_edges_from(list(unique_edges))
            removed_edges_total += len(unique_edges)

            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(
            f"[Skeleton] Ratio Pruning 완료: 삭제 경로={removed_paths}, 삭제 간선={removed_edges_total}",
            level="INFO",
        )
        return graph


class BoundaryNearPruner:
    """면형의 경계선에 너무 가깝게 생성되어 굴곡을 유발하는 노이즈 선분을 제거합니다."""
    def __init__(self, logger: Log):
        self._logger = logger
        self._policy = _BoundaryNearPolicy()

    def execute(self, graph: nx.Graph) -> nx.Graph:
        pol = self._policy
        comp_meta = self._compute_component_meta(graph)

        judged_paths = 0
        hard_removed_paths = 0
        soft_removed_edges = 0
        protected_paths = 0

        while True:
            leaf_nodes = [n for n, d in graph.degree() if d == 1]
            if not leaf_nodes:
                break

            edges_to_remove: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
            hard_edges_to_remove: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
            processed = False

            for leaf in leaf_nodes:
                path = _trace_leaf_to_junction(graph, leaf)
                if path is None or not path.edges:
                    continue

                judged_paths += 1

                comp_id = self._component_id_of_node(comp_meta, leaf)
                if comp_id is not None:
                    meta = comp_meta[comp_id]
                    if (meta["total_len"] >= pol.protect_component_min_total_len_m) or (meta["max_radius"] >= pol.protect_component_max_radius_m):
                        protected_paths += 1
                        continue

                radii = [float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in path.nodes]
                min_r = min(radii) if radii else MIN_RADIUS

                if min_r <= pol.hard_min_radius_m:
                    hard_edges_to_remove.extend(path.edges)
                    processed = True
                    hard_removed_paths += 1
                    continue

                hit = sum(1 for r in radii if r <= pol.min_radius_hit_m)
                hit_ratio = hit / max(len(radii), 1)

                if (hit_ratio >= pol.max_hit_ratio) or (hit >= pol.max_abs_hits):
                    k = min(pol.remove_leaf_edges_count, len(path.edges))
                    edges_to_remove.extend(path.edges[:k])
                    processed = True

            if not processed or (not edges_to_remove and not hard_edges_to_remove):
                break

            unique_hard = set()
            for u, v in hard_edges_to_remove:
                unique_hard.add((u, v) if u <= v else (v, u))
            if unique_hard:
                graph.remove_edges_from(list(unique_hard))

            unique_soft = set()
            for u, v in edges_to_remove:
                unique_soft.add((u, v) if u <= v else (v, u))
            if unique_soft:
                graph.remove_edges_from(list(unique_soft))
                soft_removed_edges += len(unique_soft)

            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(
            f"[Skeleton] Boundary-near pruning 완료: 강제삭제={hard_removed_paths}, 부분삭제={soft_removed_edges}",
            level="INFO",
        )
        return graph

    def _compute_component_meta(self, graph: nx.Graph) -> Dict[int, Dict[str, float]]:
        """네트워크 파편별 총 길이 및 최대 도로 폭 정보를 계산합니다."""
        comp_meta: Dict[int, Dict[str, float]] = {}
        components = list(nx.connected_components(graph))
        for cid, comp in enumerate(components):
            sub = graph.subgraph(comp)
            total_len = sum(float(data.get("weight", 0.0)) for _, _, data in sub.edges(data=True))
            max_radius = max(float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in comp) if comp else 0.0
            comp_meta[cid] = {"total_len": total_len, "max_radius": max_radius, "nodes": comp}
        return comp_meta

    def _component_id_of_node(self, comp_meta: Dict[int, Dict[str, float]], node: Tuple[float, float]) -> Optional[int]:
        """특정 노드가 속한 네트워크 파편의 ID를 반환합니다."""
        for cid, meta in comp_meta.items():
            if node in meta["nodes"]:
                return cid
        return None


class ComponentPruner:
    """교차로와 연결되지 않고 고립된 짧은 네트워크 파편들을 일괄 제거합니다."""
    def __init__(self, logger: Log):
        self._logger = logger
        self._policy = _ComponentPolicy()

    def execute(self, graph: nx.Graph) -> nx.Graph:
        removed_components = 0
        removed_edges = 0
        min_len = self._policy.min_component_total_len_m
        protect_r = self._policy.protect_component_max_radius_m

        components = list(nx.connected_components(graph))
        for comp in components:
            has_junction = any(graph.degree(n) >= 3 for n in comp)
            if has_junction:
                continue

            sub = graph.subgraph(comp)
            total_len = sum(float(data.get("weight", 0.0)) for _, _, data in sub.edges(data=True))
            max_radius = max(float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in comp) if comp else 0.0

            if (total_len >= min_len) or (max_radius >= protect_r):
                continue

            removed_edges += sub.number_of_edges()
            graph.remove_nodes_from(list(comp))
            removed_components += 1

        self._logger.log(
            f"[Skeleton] 고립 파편 제거 완료: 삭제 그룹={removed_components}, 삭제 간선={removed_edges}",
            level="INFO",
        )
        return graph


class SpurPruner:
    """교차로(Junction)에서 뻗어 나온 짧은 잔가지를 주변 가지들과의 길이를 비교하여 제거합니다."""
    def __init__(self, logger: Log):
        self._logger = logger
        self._policy = _SpurPolicy()

    def execute(self, graph: nx.Graph) -> nx.Graph:
        pol = self._policy
        removed = 0

        junctions = [n for n, d in graph.degree() if d >= 3]
        if not junctions:
            return graph

        edges_to_remove = set()

        for j in junctions:
            branches = []
            for nb in graph.neighbors(j):
                blen, is_true_spur = self._trace_branch(graph, start=j, first=nb)
                branches.append((nb, blen, is_true_spur))

            if not branches:
                continue

            max_len = max(bl for _, bl, _ in branches)

            for nb, bl, is_true_spur in branches:
                if is_true_spur and bl <= pol.abs_spur_max_len_m and bl <= max_len * pol.rel_spur_ratio:
                    u, v = j, nb
                    edges_to_remove.add((u, v) if u <= v else (v, u))

        if edges_to_remove:
            graph.remove_edges_from(list(edges_to_remove))
            removed = len(edges_to_remove)

            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(
            f"[Skeleton] 교차로 잔가지 제거 완료: 삭제 간선={removed}",
            level="INFO",
        )
        return graph

    def _trace_branch(self, graph: nx.Graph, start: Tuple[float, float], first: Tuple[float, float]) -> Tuple[float, bool]:
        """주어진 지점으로부터 가지의 끝 또는 다음 교차점까지 추적하여 길이와 잔가지 여부를 확인합니다."""
        total = float(graph.edges[start, first].get("weight", 0.0))
        prev = start
        cur = first

        while True:
            deg = graph.degree(cur)
            if deg == 1:
                return total, True
            if deg >= 3:
                return total, False

            nxts = [n for n in graph.neighbors(cur) if n != prev]
            if not nxts:
                return total, True

            nxt = nxts[0]
            total += float(graph.edges[cur, nxt].get("weight", 0.0))
            prev, cur = cur, nxt