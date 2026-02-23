"""
Service/gis_modules/validator.py

최종 산출물의 데이터 품질을 검증하고 리스크 요소를 로깅하는 품질 보증(QA) 모듈입니다.
"""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from Common.log import Log
from Service.config import GISConfig


class ResultValidator:
    """
    최종 중심선 데이터의 네트워크 연결성과 경계면 마감 상태를 검증합니다.
    """
    def __init__(self, logger: Log, config: GISConfig):
        self._logger = logger
        self._config = config

    def execute(self, final_gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame) -> None:
        """
        검증 로직을 실행하며, 데이터의 원형을 변경하지 않고 분석 결과만 로그로 출력합니다.
        """
        if final_gdf.empty:
            self._logger.log("[Validator] 검증 실패: 최종 결과 데이터가 비어있습니다.", level="WARNING")
            return

        self._logger.log("=== 최종 결과물 품질 검증(QA) 시작 ===", level="INFO")

        graph = nx.Graph()
        for geom in final_gdf.geometry:
            if geom is None or geom.is_empty or not isinstance(geom, LineString):
                continue

            p1 = (round(geom.coords[0][0], 3), round(geom.coords[0][1], 3))
            p2 = (round(geom.coords[-1][0], 3), round(geom.coords[-1][1], 3))
            graph.add_edge(p1, p2)

        errors = []

        self._check_connectivity(graph, errors)
        self._check_boundary_touch(graph, input_gdf, errors)

        if errors:
            self._logger.log(f"[Validator] 검증 완료: {len(errors)}개의 잠재적 위험 요소가 발견되었습니다.", level="WARNING")
            for err in errors[:5]:
                self._logger.log(f"  - {err}", level="WARNING")
        else:
            self._logger.log("[Validator] 검증 완료: 모든 품질 기준을 통과했습니다.", level="INFO")

    def _check_connectivity(self, graph: nx.Graph, errors: list) -> None:
        """네트워크 그래프의 연결 상태를 확인하여 분리된 파편의 존재 여부를 검사합니다."""
        components = list(nx.connected_components(graph))
        num_components = len(components)

        self._logger.log(f"[Validator] 네트워크 분리 그룹 수: {num_components}개", level="INFO")

        if num_components > 1:
            sizes = sorted([len(c) for c in components], reverse=True)
            self._logger.log(f"[Validator] 각 그룹별 노드 수: {sizes}", level="DEBUG")
            errors.append(f"네트워크가 {num_components}개의 파편으로 끊어져 있습니다.")

    def _check_boundary_touch(self, graph: nx.Graph, input_gdf: gpd.GeoDataFrame, errors: list) -> None:
        """도로의 끝점이 원본 면형의 경계선에 인접했는지 확인하여 마감 품질을 검사합니다."""
        terminal_nodes = [n for n, d in graph.degree() if d == 1]

        if not terminal_nodes:
            return

        try:
            boundary_geom = unary_union([g for g in input_gdf.geometry if g is not None]).boundary
        except Exception:
            self._logger.log("[Validator] Boundary 생성 실패로 마감 검증을 스킵합니다.", level="WARNING")
            return

        tolerance = float(getattr(self._config, "snap_threshold", 0.5))
        failed_count = 0

        for node in terminal_nodes:
            pt = Point(node)
            dist = float(boundary_geom.distance(pt))

            if dist > tolerance:
                failed_count += 1
                if failed_count <= 3:
                    errors.append(f"끝점({node})이 경계선에서 {dist:.3f}m 떨어져 있습니다. (허용치: {tolerance}m)")

        if failed_count == 0:
            self._logger.log(f"[Validator] 마감 품질 양호: {len(terminal_nodes)}개 끝점 모두 경계선에 안착함.", level="INFO")
        else:
            self._logger.log(f"[Validator] 마감 불량 의심: {len(terminal_nodes)}개 중 {failed_count}개가 경계에 닿지 않음.", level="WARNING")