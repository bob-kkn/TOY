"""
Service/gis_modules/skeleton/processor.py

면형 데이터로부터 원시 뼈대를 추출하고 정제하는 파이프라인 제어 모듈입니다.
"""
from __future__ import annotations

import geopandas as gpd

from Common.log import Log
from Function.decorators import log_execution_time, safe_run
from Service.config import GISConfig

from .generator import VoronoiGenerator
from .graph_builder import SkeletonGraphBuilder
from .pruners import (
    RatioPruner,
    BoundaryNearPruner,
    ComponentPruner,
    SpurPruner
)


class SkeletonProcessor:
    """
    면형 입력부터 정제된 중심선 출력까지의 전체 공정을 제어합니다.
    """
    def __init__(self, logger: Log, config: GISConfig):
        self._logger = logger
        self._config = config

        self._generator = VoronoiGenerator(logger)
        self._builder = SkeletonGraphBuilder(logger)

        self._pruners = [
            RatioPruner(logger),
            BoundaryNearPruner(logger),
            ComponentPruner(logger),
            SpurPruner(logger)
        ]

    @safe_run
    @log_execution_time
    def execute(self, input_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        입력 폴리곤 데이터로부터 보로노이 다이어그램 기반의 정제된 중심선을 추출합니다.

        Args:
            input_gdf (gpd.GeoDataFrame): 원본 면형 데이터

        Returns:
            gpd.GeoDataFrame: 정제 공정이 완료된 중심선 데이터
        """
        if input_gdf.empty:
            self._logger.log("입력 데이터가 비어있어 처리를 중단합니다.", level="WARNING")
            return gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)

        merged_polygon = self._generator.merge_polygons(input_gdf)
        if merged_polygon is None or merged_polygon.is_empty:
            self._logger.log("면형 통합 결과가 비어있습니다.", level="WARNING")
            return gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)

        raw_lines = self._generator.generate_voronoi_skeleton(merged_polygon)
        self._logger.log(f"[Skeleton] Voronoi 원시 뼈대 추출: {len(raw_lines)}개 세그먼트", level="INFO")
        if not raw_lines:
            return gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)

        graph = self._builder.build_context_aware_graph(raw_lines, merged_polygon)

        for pruner in self._pruners:
            graph = pruner.execute(graph)

        final_graph = self._builder.merge_degree_2_nodes(graph)
        final_lines = self._builder.export_graph_to_lines(final_graph)

        self._logger.log(f"[Skeleton] 최종 중심선 생성 완료: {len(final_lines)}개 객체", level="INFO")

        return gpd.GeoDataFrame(geometry=final_lines, crs=input_gdf.crs)