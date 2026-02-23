"""
Service/gis_modules/skeleton/pruners.py

중심선 생성 과정에서 발생하는 잔가지, 경계 근접 노이즈 등을 제거하는 정제 전략 모듈입니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import networkx as nx

from Common.log import Log
from .policy import SkeletonPolicy

MIN_RADIUS = 0.1


@dataclass(frozen=True)
class _EdgePath:
    nodes: List[Tuple[float, float]]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]]
    total_length: float
    junction_node: Tuple[float, float]
    junction_radius: float


def _trace_leaf_to_junction(graph: nx.Graph, leaf: Tuple[float, float]) -> Optional[_EdgePath]:
    current = leaf
    visited = {current}
    nodes = [current]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    total_length = 0.0

    while True:
        neighbors = list(graph.neighbors(current))
        next_candidates = [n for n in neighbors if n not in visited]

        if not next_candidates:
            junction_radius = float(graph.nodes[current].get("radius", MIN_RADIUS))
            return _EdgePath(nodes=nodes, edges=edges, total_length=total_length, junction_node=current, junction_radius=junction_radius)

        nxt = next_candidates[0]
        total_length += float(graph.edges[current, nxt].get("weight", 0.0))
        edges.append((current, nxt))
        current = nxt
        visited.add(current)
        nodes.append(current)

        if graph.degree(current) >= 3:
            junction_radius = float(graph.nodes[current].get("radius", MIN_RADIUS))
            return _EdgePath(nodes=nodes, edges=edges, total_length=total_length, junction_node=current, junction_radius=junction_radius)


class RatioPruner:
    def __init__(self, logger: Log, policy: SkeletonPolicy):
        self._logger = logger
        self._policy = policy

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
                threshold_len = path.junction_radius * self._policy.prune_ratio_limit
                if path.total_length < threshold_len:
                    edges_to_remove.extend(path.edges)
                    processed = True
                    removed_paths += 1

            if not processed or not edges_to_remove:
                break

            unique_edges = set((u, v) if u <= v else (v, u) for u, v in edges_to_remove)
            graph.remove_edges_from(list(unique_edges))
            removed_edges_total += len(unique_edges)

            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(f"[Skeleton] Ratio Pruning 완료: 삭제 경로={removed_paths}, 삭제 간선={removed_edges_total}", level="INFO")
        return graph


class BoundaryNearPruner:
    def __init__(self, logger: Log, policy: SkeletonPolicy):
        self._logger = logger
        self._policy = policy

    def execute(self, graph: nx.Graph) -> nx.Graph:
        comp_meta = self._compute_component_meta(graph)
        hard_removed_paths = 0
        soft_removed_edges = 0

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

                comp_id = self._component_id_of_node(comp_meta, leaf)
                if comp_id is not None:
                    meta = comp_meta[comp_id]
                    if (
                        meta["total_len"] >= self._policy.boundary_protect_component_min_total_len_m
                        or meta["max_radius"] >= self._policy.boundary_protect_component_max_radius_m
                    ):
                        continue

                radii = [float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in path.nodes]
                hit = sum(1 for r in radii if r <= self._policy.boundary_min_radius_hit_m)
                hit_ratio = hit / max(len(radii), 1)

                if path.junction_radius <= self._policy.boundary_hard_min_radius_m:
                    hard_edges_to_remove.extend(path.edges)
                    hard_removed_paths += 1
                    processed = True
                    continue

                if (hit_ratio >= self._policy.boundary_max_hit_ratio) or (hit >= self._policy.boundary_max_abs_hits):
                    k = min(self._policy.boundary_remove_leaf_edges_count, len(path.edges))
                    edges_to_remove.extend(path.edges[:k])
                    processed = True

            if not processed or (not edges_to_remove and not hard_edges_to_remove):
                break

            unique_hard = set((u, v) if u <= v else (v, u) for u, v in hard_edges_to_remove)
            if unique_hard:
                graph.remove_edges_from(list(unique_hard))

            unique_soft = set((u, v) if u <= v else (v, u) for u, v in edges_to_remove)
            if unique_soft:
                graph.remove_edges_from(list(unique_soft))
                soft_removed_edges += len(unique_soft)

            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(f"[Skeleton] Boundary-near pruning 완료: 강제삭제={hard_removed_paths}, 부분삭제={soft_removed_edges}", level="INFO")
        return graph

    def _compute_component_meta(self, graph: nx.Graph) -> Dict[int, Dict[str, float]]:
        comp_meta: Dict[int, Dict[str, float]] = {}
        for cid, comp in enumerate(nx.connected_components(graph)):
            sub = graph.subgraph(comp)
            total_len = sum(float(data.get("weight", 0.0)) for _, _, data in sub.edges(data=True))
            max_radius = max(float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in comp) if comp else 0.0
            comp_meta[cid] = {"total_len": total_len, "max_radius": max_radius, "nodes": comp}
        return comp_meta

    def _component_id_of_node(self, comp_meta: Dict[int, Dict[str, float]], node: Tuple[float, float]) -> Optional[int]:
        for cid, meta in comp_meta.items():
            if node in meta["nodes"]:
                return cid
        return None


class ComponentPruner:
    def __init__(self, logger: Log, policy: SkeletonPolicy):
        self._logger = logger
        self._policy = policy

    def execute(self, graph: nx.Graph) -> nx.Graph:
        removed_components = 0
        removed_edges = 0

        for comp in list(nx.connected_components(graph)):
            if any(graph.degree(n) >= 3 for n in comp):
                continue
            sub = graph.subgraph(comp)
            total_len = sum(float(data.get("weight", 0.0)) for _, _, data in sub.edges(data=True))
            max_radius = max(float(graph.nodes[n].get("radius", MIN_RADIUS)) for n in comp) if comp else 0.0

            if total_len >= self._policy.component_min_total_len_m or max_radius >= self._policy.component_protect_max_radius_m:
                continue

            removed_edges += sub.number_of_edges()
            graph.remove_nodes_from(list(comp))
            removed_components += 1

        self._logger.log(f"[Skeleton] 고립 파편 제거 완료: 삭제 그룹={removed_components}, 삭제 간선={removed_edges}", level="INFO")
        return graph


class SpurPruner:
    def __init__(self, logger: Log, policy: SkeletonPolicy):
        self._logger = logger
        self._policy = policy

    def execute(self, graph: nx.Graph) -> nx.Graph:
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
                if is_true_spur and bl <= self._policy.spur_abs_max_len_m and bl <= max_len * self._policy.spur_rel_ratio:
                    edges_to_remove.add((j, nb) if j <= nb else (nb, j))

        if edges_to_remove:
            graph.remove_edges_from(list(edges_to_remove))
            isolates = list(nx.isolates(graph))
            if isolates:
                graph.remove_nodes_from(isolates)

        self._logger.log(f"[Skeleton] 교차로 잔가지 제거 완료: 삭제 간선={len(edges_to_remove)}", level="INFO")
        return graph

    def _trace_branch(self, graph: nx.Graph, start: Tuple[float, float], first: Tuple[float, float]) -> Tuple[float, bool]:
        total = float(graph.edges[start, first].get("weight", 0.0))
        prev, cur = start, first
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
