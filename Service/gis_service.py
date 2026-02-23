"""
Service/gis_service.py

GIS 파이프라인의 전체 공정을 제어하는 서비스 모듈입니다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd

from Common.log import Log
from Function.utils import get_runtime_base_path
from Function.decorators import log_execution_time, safe_run
from Service.schemas import FileLoadRequest, FileSaveRequest
from Service.gis_modules import GISIO, ResultValidator, SkeletonProcessor, TopologyProcessor


class GISService:
    """
    GIS 파이프라인의 실행을 관리하는 메인 서비스 클래스입니다.
    """

    def __init__(
        self,
        logger: Log,
        gis_io: GISIO,
        skeleton_processor: SkeletonProcessor,
        topology_processor: TopologyProcessor,
        validator: ResultValidator,
        config: Optional[object] = None,
    ):
        self._logger = logger
        self._gis_io = gis_io
        self._skeleton = skeleton_processor
        self._topology = topology_processor
        self._validator = validator
        self._config = config

    @safe_run
    @log_execution_time
    def run_pipeline(self, input_path: str) -> str:
        """
        입력 경로로부터 데이터를 로드하여 중심선 추출 및 토폴로지 정제 파이프라인을 실행합니다.
        """
        target_path = Path(input_path)

        output_dir = get_runtime_base_path() / "Result"
        output_dir.mkdir(parents=True, exist_ok=True)

        load_request = FileLoadRequest(file_path=target_path)
        gdf_input = self._gis_io.load(load_request)

        gdf_skeleton = self._skeleton.execute(gdf_input)

        debug_export = bool(getattr(self._config, "debug_export_intermediate", False))

        if debug_export:
            stage1_gdf, stage2_gdf, final_gdf = self._topology.execute_with_stages(gdf_skeleton, gdf_input)

            self._save_stage(output_dir, target_path.stem, "01_skeleton", gdf_skeleton, gdf_input.crs)
            if stage1_gdf is not None:
                self._save_stage(output_dir, target_path.stem, "02_planarized", stage1_gdf, gdf_input.crs)
            if stage2_gdf is not None:
                self._save_stage(output_dir, target_path.stem, "03_cleaned", stage2_gdf, gdf_input.crs)
            self._save_stage(output_dir, target_path.stem, "04_final_raw", final_gdf, gdf_input.crs)
        else:
            final_gdf = self._topology.execute(gdf_skeleton, gdf_input)

        self._validator.execute(final_gdf, gdf_input)

        final_clean = self._drop_debug_columns(final_gdf)
        output_path = output_dir / f"{target_path.stem}_centerline.shp"

        save_request = FileSaveRequest(output_path=output_path)
        final_path = self._gis_io.save(final_clean, save_request)

        return str(final_path)

    def _save_stage(self, output_dir: Path, stem: str, stage: str, gdf: gpd.GeoDataFrame, crs) -> None:
        """파이프라인 중간 단계의 결과물을 파일로 저장합니다."""
        if gdf is None or gdf.empty:
            return

        stage_path = output_dir / f"{stem}_{stage}.shp"
        stage_gdf = gdf[["geometry"]].copy()
        stage_gdf.crs = crs

        try:
            stage_gdf.to_file(stage_path, driver="ESRI Shapefile", encoding="cp949")
            self._logger.log(f"[Debug] 저장 완료: {stage_path.name}", level="INFO")
        except Exception as e:
            self._logger.log(f"[Debug] 저장 실패: {stage_path.name} - {e}", level="WARNING")

    def _drop_debug_columns(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """데이터 프레임에서 알고리즘 수행 중 생성된 내부 디버그용 컬럼들을 제거합니다."""
        if gdf is None or gdf.empty:
            return gdf

        drop_cols = [c for c in gdf.columns if c != "geometry" and c.startswith(("is_", "terminal_"))]
        if not drop_cols:
            return gdf

        return gdf.drop(columns=drop_cols, errors="ignore").copy()