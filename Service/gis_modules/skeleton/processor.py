"""
Service/gis_modules/skeleton/processor.py

면형 데이터로부터 원시 뼈대를 추출하고 정제하는 파이프라인 제어 모듈입니다.
"""
from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import geopandas as gpd
from shapely.geometry import LineString, MultiPolygon, Polygon

from Common.log import Log
from Function.decorators import log_execution_time, safe_run
from Service.config import GISConfig

from .generator import VoronoiGenerator
from .graph_builder import SkeletonGraphBuilder
from .policy import SkeletonPolicy
from .pruners import RatioPruner, BoundaryNearPruner, ComponentPruner, SpurPruner
from .selector import SkeletonCandidateSelector


class SkeletonProcessor:
    def __init__(self, logger: Log, config: GISConfig):
        self._logger = logger
        self._config = config
        self._generator = VoronoiGenerator(logger)
        self._builder = SkeletonGraphBuilder(logger)
        self._selector = SkeletonCandidateSelector(logger)
        self._last_stage_meta: List[Dict[str, Any]] = []

    @safe_run
    @log_execution_time
    def execute(
        self,
        input_gdf: gpd.GeoDataFrame,
        return_stage_meta: bool = False,
        stage_meta_output_path: Optional[str] = None,
    ) -> Union[gpd.GeoDataFrame, tuple[gpd.GeoDataFrame, List[Dict[str, Any]]]]:
        self._last_stage_meta = []
        if input_gdf.empty:
            self._logger.log("입력 데이터가 비어있어 처리를 중단합니다.", level="WARNING")
            empty_gdf = gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)
            return self._finalize_result(empty_gdf, return_stage_meta, stage_meta_output_path)

        widths = self._extract_width_samples(input_gdf)
        policy = SkeletonPolicy.from_width_distribution(widths)
        self._logger.log(f"[Skeleton:Policy] selected={policy.name}, median_width={self._median(widths):.2f}", level="INFO")

        pruners = [
            RatioPruner(self._logger, policy),
            BoundaryNearPruner(self._logger, policy),
            ComponentPruner(self._logger, policy),
            SpurPruner(self._logger, policy),
        ]

        merged_polygon = self._generator.merge_polygons(input_gdf, policy)
        if merged_polygon is None or merged_polygon.is_empty:
            self._logger.log("면형 통합 결과가 비어있습니다.", level="WARNING")
            empty_gdf = gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)
            return self._finalize_result(empty_gdf, return_stage_meta, stage_meta_output_path)
        self._log_stage_meta("00_merge", {"parts": len(self._to_polygons(merged_polygon))})

        stable_polygon = self._generator.stabilize_geometry(merged_polygon, policy)
        self._log_stage_meta("01_preprocess", {"parts": len(self._to_polygons(stable_polygon))})

        raw_voronoi = self._generator.generate_voronoi_skeleton(stable_polygon, policy)
        raw_boundary_pair = self._generator.generate_boundary_pair_centerlines(stable_polygon, policy)

        selected_voronoi = self._selector.select(raw_voronoi, stable_polygon, policy, "voronoi")
        selected_boundary_pair = self._selector.select(raw_boundary_pair, stable_polygon, policy, "boundary_pair")

        raw_lines = [ln for ln in (selected_voronoi + selected_boundary_pair) if ln is not None and not ln.is_empty]
        self._log_stage_meta(
            "02_candidates",
            {
                "voronoi_raw": len(raw_voronoi),
                "voronoi_selected": len(selected_voronoi),
                "boundary_pair_raw": len(raw_boundary_pair),
                "boundary_pair_selected": len(selected_boundary_pair),
                "total": len(raw_lines),
            },
        )

        if not raw_lines:
            empty_gdf = gpd.GeoDataFrame(columns=["geometry"], crs=input_gdf.crs)
            return self._finalize_result(empty_gdf, return_stage_meta, stage_meta_output_path)

        graph = self._builder.build_context_aware_graph(raw_lines, stable_polygon)
        self._log_stage_meta("03_graph_build", {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()})

        for pruner in pruners:
            graph = pruner.execute(graph)

        graph = self._builder.merge_degree_2_nodes(graph)
        graph = self._builder.separate_parallel_and_reconnect(graph, policy, stable_polygon)
        graph = self._builder.smooth_by_direction_field(graph, policy)
        self._log_stage_meta("04_graph_refine", {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()})

        final_lines = self._builder.export_graph_to_lines(graph)
        final_lines = [ln for ln in final_lines if ln is not None and isinstance(ln, LineString) and ln.length >= policy.postprocess_min_len_m]
        self._log_stage_meta("05_finalize", {"line_count": len(final_lines), "min_len": policy.postprocess_min_len_m})

        output_gdf = gpd.GeoDataFrame(geometry=final_lines, crs=input_gdf.crs)
        return self._finalize_result(output_gdf, return_stage_meta, stage_meta_output_path)

    def get_last_stage_meta(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._last_stage_meta]

    def _extract_width_samples(self, gdf: gpd.GeoDataFrame) -> List[float]:
        widths: List[float] = []
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            polys = self._to_polygons(geom)
            for poly in polys:
                try:
                    rect = poly.minimum_rotated_rectangle
                    coords = list(rect.exterior.coords)
                    if len(coords) < 5:
                        continue
                    edges = []
                    for i in range(4):
                        dx = coords[i + 1][0] - coords[i][0]
                        dy = coords[i + 1][1] - coords[i][1]
                        edges.append(math.hypot(dx, dy))
                    widths.append(min(edges))
                except Exception:
                    continue
        return widths

    def _median(self, values: List[float]) -> float:
        if not values:
            return 0.0
        vals = sorted(values)
        return vals[len(vals) // 2]

    def _to_polygons(self, geom) -> List[Polygon]:
        if isinstance(geom, Polygon):
            return [geom]
        if isinstance(geom, MultiPolygon):
            return list(geom.geoms)
        return []

    def _log_stage_meta(self, stage: str, meta: Dict[str, object]) -> None:
        stage_record = {"stage": stage, "meta": dict(meta)}
        self._last_stage_meta.append(stage_record)
        items = ", ".join([f"{k}={v}" for k, v in meta.items()])
        self._logger.log(f"[Skeleton:Stage:{stage}] {items}", level="INFO")

    def _save_stage_meta(self, output_path: str) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._last_stage_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _finalize_result(
        self,
        gdf: gpd.GeoDataFrame,
        return_stage_meta: bool,
        stage_meta_output_path: Optional[str],
    ) -> Union[gpd.GeoDataFrame, tuple[gpd.GeoDataFrame, List[Dict[str, Any]]]]:
        if stage_meta_output_path:
            self._save_stage_meta(stage_meta_output_path)
        if return_stage_meta:
            return gdf, self.get_last_stage_meta()
        return gdf
