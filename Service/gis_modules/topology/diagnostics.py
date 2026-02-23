"""
Service/gis_modules/topology/diagnostics.py

위상 정제 결과의 통계적 수치와 품질 리스크 요소를 분석하여 로그로 출력하는 진단 모듈입니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import unary_union

from Common.log import Log


@dataclass(frozen=True)
class TopologyDiagnosticsPolicy:
    """진단 시 리스크 판정 및 샘플링 제한을 위한 임계값 설정입니다."""
    boundary_dist_threshold_m: float = 0.25
    short_edge_threshold_m: float = 3.0
    sample_points: int = 5
    top_n_suspects: int = 20
    max_edges_for_boundary_scan: int = 20000


class TopologyDiagnostics:
    """
    위상 그래프의 노드 연결 상태와 도로 경계면과의 거리를 분석하여 품질 상태를 보고합니다.
    """

    def __init__(self, logger: Log, policy: Optional[TopologyDiagnosticsPolicy] = None):
        self._logger = logger
        self._policy = policy or TopologyDiagnosticsPolicy()

    def report(self, G: nx.Graph, edges_gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame) -> None:
        """
        위상 요약 통계, 간선 길이 분포, 경계면 근접 리스크 후보군을 순차적으로 진단하여 로깅합니다.
        """
        if edges_gdf.empty:
            self._logger.log("[Topology:Diag] 분석 대상 데이터가 비어있습니다.", level="WARNING")
            return

        self._log_graph_summary(G)
        self._log_edge_length_summary(edges_gdf)

        if len(edges_gdf) > self._policy.max_edges_for_boundary_scan:
            self._logger.log(
                f"[Topology:Diag] 데이터 과다로 경계 스캔 중단 (최대 {self._policy.max_edges_for_boundary_scan}개 허용)",
                level="WARNING",
            )
            return

        boundary = self._build_boundary(input_gdf)
        if boundary is None or boundary.is_empty:
            self._logger.log("[Topology:Diag] 경계면 생성 불가로 거리 진단을 건너뜁니다.", level="WARNING")
            return

        diag_df = self._build_edge_diagnostics(G, edges_gdf, boundary)

        self._log_boundary_summary(diag_df)
        self._log_risk_candidates(diag_df)

    def _log_graph_summary(self, G: nx.Graph) -> None:
        """그래프의 위상학적 구성 요소(노드 차수별 개수, 컴포넌트 수)를 기록합니다."""
        degrees = [d for _, d in G.degree()]
        d1 = degrees.count(1)
        d2 = degrees.count(2)
        d3p = sum(1 for d in degrees if d >= 3)

        comps = list(nx.connected_components(G))
        self._logger.log(
            f"[Topology:Diag][Graph] 노드={len(G.nodes)} 간선={len(G.edges)} "
            f"그룹={len(comps)} 단말(D1)={d1} 통과(D2)={d2} 교차(D3+)={d3p}",
            level="INFO",
        )

    def _log_edge_length_summary(self, edges_gdf: gpd.GeoDataFrame) -> None:
        """간선 길이에 대한 백분위수 분포를 기록합니다."""
        lengths = edges_gdf.geometry.length
        desc = lengths.describe(percentiles=[0.01, 0.05, 0.1, 0.5, 0.9, 0.95, 0.99]).to_dict()
        self._logger.log(
            "[Topology:Diag][EdgeLen] "
            + " ".join([f"{k}={float(v):.3f}" for k, v in desc.items() if k != "count"]),
            level="INFO",
        )

    def _build_boundary(self, input_gdf: gpd.GeoDataFrame):
        """입력 폴리곤들로부터 분석 기준이 될 경계 외곽선을 생성합니다."""
        try:
            geoms = [g for g in input_gdf.geometry if g is not None and not g.is_empty]
            if not geoms:
                return None
            merged = unary_union(geoms)
            return merged.boundary
        except Exception:
            return None

    def _build_edge_diagnostics(self, G: nx.Graph, edges_gdf: gpd.GeoDataFrame, boundary) -> pd.DataFrame:
        """각 간선별 위상 특성과 경계 거리를 계산하여 데이터프레임으로 구축합니다."""
        degree_map = dict(G.degree())

        def node_key(x: float, y: float) -> Tuple[float, float]:
            return (round(float(x), 3), round(float(y), 3))

        rows: List[Dict] = []
        k = max(1, int(self._policy.sample_points))

        for idx, geom in enumerate(edges_gdf.geometry):
            if geom is None or geom.is_empty or not isinstance(geom, LineString):
                continue

            u = node_key(geom.coords[0][0], geom.coords[0][1])
            v = node_key(geom.coords[-1][0], geom.coords[-1][1])

            du = int(degree_map.get(u, 0))
            dv = int(degree_map.get(v, 0))

            length_m = float(geom.length)
            min_bd = self._min_boundary_dist(geom, boundary, k)

            is_leaf_edge = (du == 1) or (dv == 1)
            is_chain_edge = (max(du, dv) <= 2)

            rows.append(
                {
                    "idx": idx,
                    "length_m": length_m,
                    "min_bd_m": min_bd,
                    "deg_u": du,
                    "deg_v": dv,
                    "is_leaf_edge": is_leaf_edge,
                    "is_chain_edge": is_chain_edge,
                }
            )

        return pd.DataFrame(rows)

    def _min_boundary_dist(self, line: LineString, boundary, sample_points: int) -> float:
        """선형 객체 위의 샘플 포인트들을 추출하여 경계선과의 최소 거리를 측정합니다."""
        if sample_points <= 1:
            p = line.interpolate(0.5, normalized=True)
            return float(boundary.distance(p))

        min_d = float("inf")
        for i in range(sample_points):
            t = i / (sample_points - 1)
            p = line.interpolate(t, normalized=True)
            d = float(boundary.distance(p))
            if d < min_d:
                min_d = d
                if min_d == 0.0:
                    break
        return min_d

    def _log_boundary_summary(self, df: pd.DataFrame) -> None:
        """경계선 근접 정도에 대한 요약 통계를 기록합니다."""
        if df.empty:
            return

        desc = df["min_bd_m"].describe(percentiles=[0.01, 0.05, 0.1, 0.5, 0.9, 0.95, 0.99]).to_dict()
        th = float(self._policy.boundary_dist_threshold_m)
        near_cnt = int((df["min_bd_m"] < th).sum())

        leaf_near = int(((df["min_bd_m"] < th) & (df["is_leaf_edge"])).sum())
        chain_near = int(((df["min_bd_m"] < th) & (df["is_chain_edge"])).sum())

        self._logger.log(
            "[Topology:Diag][Boundary] "
            + " ".join([f"{k}={float(v):.3f}" for k, v in desc.items() if k != "count"])
            + f" | 근접( <{th}m )={near_cnt} (단말근접={leaf_near}, 단순근접={chain_near})",
            level="INFO",
        )

    def _log_risk_candidates(self, df: pd.DataFrame) -> None:
        """길이가 짧고 경계에 인접하여 노이즈로 의심되는 상위 후보군을 기록합니다."""
        if df.empty:
            return

        th_bd = float(self._policy.boundary_dist_threshold_m)
        th_len = float(self._policy.short_edge_threshold_m)

        cand = df[(df["min_bd_m"] < th_bd) & (df["length_m"] < th_len)].copy()
        cand = cand.sort_values(["min_bd_m", "length_m"], ascending=[True, True])

        self._logger.log(
            f"[Topology:Diag][Risk] 잠재적 노이즈 후보군(경계<{th_bd}m 및 길이<{th_len}m)={len(cand)}개",
            level="INFO",
        )

        top_n = int(self._policy.top_n_suspects)
        if len(cand) == 0:
            return

        for _, r in cand.head(top_n).iterrows():
            self._logger.log(
                f"[Topology:Diag][RiskTop] 인덱스={int(r['idx'])} 길이={float(r['length_m']):.3f}m "
                f"경계거리={float(r['min_bd_m']):.3f}m 차수=({int(r['deg_u'])},{int(r['deg_v'])})",
                level="INFO",
            )