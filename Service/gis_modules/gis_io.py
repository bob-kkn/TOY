"""
Service/gis_modules/gis_io.py

GIS 데이터(SHP)의 입출력을 담당하는 모듈입니다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Set

import geopandas as gpd

from Common.log import Log
from Function.decorators import log_execution_time, safe_run
from Service.schemas import FileLoadRequest, FileSaveRequest


class GISIO:
    """
    SHP 파일의 로드 및 저장을 처리하며 데이터의 유효성을 검증합니다.
    """

    _ALLOWED_LINE_TYPES: Set[str] = {"LineString", "MultiLineString"}

    def __init__(self, logger: Log):
        self._logger = logger

    @safe_run
    @log_execution_time
    def load(self, request: FileLoadRequest) -> gpd.GeoDataFrame:
        """
        SHP 파일을 로드하고 데이터 존재 여부, 좌표계(CRS) 및 미터 단위 여부를 검증합니다.

        Args:
            request (FileLoadRequest): 파일 경로를 포함한 로드 요청 객체

        Returns:
            gpd.GeoDataFrame: 로드된 지리 정보 데이터
        """
        file_path = request.file_path.expanduser().resolve()

        gdf = gpd.read_file(file_path, encoding="cp949")

        if gdf.empty:
            raise ValueError("로드된 데이터가 비어있습니다.")

        if gdf.crs is None:
            raise ValueError("입력 데이터에 CRS가 없습니다.")

        crs_name = getattr(gdf.crs, "name", None) or "Unknown"
        epsg = self._try_to_epsg(gdf)

        self._logger.log(f"데이터 로드 상세 - 객체 수: {len(gdf)}, CRS: {crs_name}, EPSG: {epsg}", level="INFO")

        if not self._is_meter_unit(gdf):
            raise ValueError(f"입력 CRS 단위가 미터가 아닙니다. 현재 CRS: {gdf.crs}")

        return gdf

    @safe_run
    @log_execution_time
    def save(self, gdf: gpd.GeoDataFrame, request: FileSaveRequest) -> Path:
        """
        데이터를 선형 geometry 여부 확인 후 지정된 경로에 SHP 파일로 저장합니다.

        Args:
            gdf (gpd.GeoDataFrame): 저장할 데이터
            request (FileSaveRequest): 저장 경로를 포함한 요청 객체

        Returns:
            Path: 저장된 파일의 경로
        """
        output_path = request.output_path.expanduser().resolve()

        if gdf.empty:
            self._logger.log("저장할 데이터가 비어있습니다.", level="WARNING")

        self._validate_line_geometries(gdf)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        gdf.to_file(output_path, driver="ESRI Shapefile", encoding="cp949")

        self._logger.log(f"저장 완료: {output_path}", level="INFO")
        return output_path

    def _try_to_epsg(self, gdf: gpd.GeoDataFrame) -> Optional[int]:
        """좌표계 정보를 EPSG 코드로 변환 시도합니다."""
        try:
            if gdf.crs is None:
                return None
            return gdf.crs.to_epsg()
        except Exception:
            return None

    def _is_meter_unit(self, gdf: gpd.GeoDataFrame) -> bool:
        """좌표계의 단위가 미터(Metre/Meter)인지 확인합니다."""
        if gdf.crs is None:
            return False

        try:
            wkt = gdf.crs.to_wkt()
        except Exception:
            wkt = str(gdf.crs)

        wkt_lower = wkt.lower()
        if 'unit["metre"' in wkt_lower or 'unit["meter"' in wkt_lower:
            return True
        if "unit[metre" in wkt_lower or "unit[meter" in wkt_lower:
            return True

        return False

    def _validate_line_geometries(self, gdf: gpd.GeoDataFrame) -> None:
        """데이터의 geometry 타입이 LineString 또는 MultiLineString인지 검증합니다."""
        if gdf.empty:
            return

        geom_types = set(gdf.geometry.geom_type.unique())
        invalid = geom_types - self._ALLOWED_LINE_TYPES
        if invalid:
            raise ValueError(f"저장 대상 geometry 타입이 선형이 아닙니다. 허용되지 않는 타입: {sorted(invalid)}")