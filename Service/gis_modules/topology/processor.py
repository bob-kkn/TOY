"""
Service/gis_modules/topology/processor.py

원시 중심선을 평면화, 정제, 직선화 단계를 거쳐 최적의 위상 네트워크로 변환하는 오케스트레이터 모듈입니다.
"""
from __future__ import annotations

from typing import List, Tuple

import geopandas as gpd
import momepy
from shapely.geometry import LineString, MultiLineString

from Common.log import Log
from Function.decorators import log_execution_time, safe_run
from Service.config import GISConfig

from .strategies import (
    CoordinateSnapper,
    Planarizer,
    IntersectionMerger,
    IntersectionSmoother,
    NetworkSimplifier
)
from .cleaners import (
    SpurCleaner,
    TerminalForkCleaner,
    TopologyCleaner
)
from .diagnostics import TopologyDiagnostics


class TopologyProcessor:
    """
    설정된 전략에 따라 토폴로지 파이프라인의 각 단계를 순차적으로 실행합니다.
    """
    def __init__(
            self,
            logger: Log,
            config: GISConfig,
            snapper: CoordinateSnapper,
            planarizer: Planarizer,
            merger: IntersectionMerger,
            fork_cleaner: TerminalForkCleaner,
            spur_cleaner: SpurCleaner,
            smoother: IntersectionSmoother,
            cleaner: TopologyCleaner,
            simplifier: NetworkSimplifier,
            diagnostics: TopologyDiagnostics,
    ):
        self._logger = logger
        self._config = config
        self._snapper = snapper
        self._planarizer = planarizer
        self._merger = merger
        self._fork_cleaner = fork_cleaner
        self._spur_cleaner = spur_cleaner
        self._smoother = smoother
        self._cleaner = cleaner
        self._simplifier = simplifier
        self._diagnostics = diagnostics

    @safe_run
    @log_execution_time
    def execute(self, skeleton_gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """토폴로지 정제 파이프라인을 실행하여 최종 결과물만 반환합니다."""
        _stage1, _stage2, final = self._run_with_stages(skeleton_gdf, input_gdf)
        return final

    @safe_run
    @log_execution_time
    def execute_with_stages(
            self, skeleton_gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame
    ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """디버그를 위해 단계별 중간 산출물을 포함하여 파이프라인을 실행합니다."""
        return self._run_with_stages(skeleton_gdf, input_gdf)

    def _run_with_stages(
            self, skeleton_gdf: gpd.GeoDataFrame, input_gdf: gpd.GeoDataFrame
    ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """좌표 보정부터 최종 직선화까지의 세부 공정을 제어합니다."""

        if skeleton_gdf.empty:
            self._logger.log("[Topology] 입력 skeleton_gdf가 비어있습니다.", level="WARNING")
            empty = gpd.GeoDataFrame(columns=["geometry"], crs=skeleton_gdf.crs)
            return empty, empty, empty

        self._logger.log("=== [Topology Pipeline] 시작 ===", level="INFO")

        snapped_gdf = self._snapper.execute(skeleton_gdf)

        raw_lines = self._extract_lines(snapped_gdf)
        if not raw_lines:
            self._logger.log("[Topology] 변환할 선분이 없습니다.", level="WARNING")
            empty = gpd.GeoDataFrame(columns=["geometry"], crs=skeleton_gdf.crs)
            return empty, empty, empty

        stage1_gdf = self._planarizer.execute(raw_lines, crs=skeleton_gdf.crs)

        merged_gdf = self._merger.execute(stage1_gdf, input_gdf)

        fork_cleaned_gdf = self._fork_cleaner.execute(merged_gdf, input_gdf)

        spur_cleaned_gdf = self._spur_cleaner.execute(fork_cleaned_gdf)

        smoothed_gdf = self._smoother.execute(spur_cleaned_gdf)

        stage2_gdf = self._cleaner.execute(smoothed_gdf)

        final_gdf = self._simplifier.execute(stage2_gdf)

        try:
            G = momepy.gdf_to_nx(final_gdf, approach="primal")
            self._diagnostics.report(G, final_gdf, input_gdf)
        except Exception as e:
            self._logger.log(f"[Topology:Diag] 진단 로그 출력 실패: {e}", level="WARNING")

        self._logger.log("=== [Topology Pipeline] 완료 ===", level="INFO")

        return stage1_gdf, stage2_gdf, final_gdf

    def _extract_lines(self, gdf: gpd.GeoDataFrame) -> List[LineString]:
        """GeoDataFrame의 geometry 컬럼에서 유효한 선형 객체들을 추출합니다."""
        raw_lines: List[LineString] = []
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, MultiLineString):
                raw_lines.extend([ln for ln in geom.geoms if ln is not None and not ln.is_empty])
            elif isinstance(geom, LineString):
                raw_lines.append(geom)
        return raw_lines