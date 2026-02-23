"""
Service/gis_modules/skeleton/generator.py

입력 면형(Polygon)을 병합하고 Voronoi 다이어그램 기반의 원시 뼈대(LineString)를 생성합니다.
"""
from __future__ import annotations

from typing import Any, List, Optional

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Polygon, MultiPolygon
from shapely.ops import unary_union, voronoi_diagram

from Common.log import Log

DENSITY_INTERVAL = 0.5


class VoronoiGenerator:
    """
    Polygon 데이터에서 Voronoi 다이어그램을 활용해 중심선(Skeleton) 후보군을 생성하는 클래스입니다.
    """

    def __init__(self, logger: Log):
        self._logger = logger

    def merge_polygons(self, gdf: gpd.GeoDataFrame) -> Optional[Any]:
        """
        여러 면형을 하나의 형상으로 통합하고 스무딩 처리를 수행합니다.

        Args:
            gdf (gpd.GeoDataFrame): 원본 입력 데이터

        Returns:
            Optional[Any]: 병합된 단일 Geometry 객체
        """
        geoms = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]
        if not geoms:
            return None

        merged = unary_union(geoms)
        try:
            merged = merged.buffer(0.1).buffer(-0.1)
            if hasattr(merged, "is_valid") and not merged.is_valid:
                merged = merged.buffer(0)
        except Exception as e:
            self._logger.log(f"[Skeleton] 면형 스무딩 실패: {e}", level="WARNING")

        return merged

    def generate_voronoi_skeleton(self, geom: Any) -> List[LineString]:
        """
        통합된 면형의 경계를 조밀화하고 Voronoi 다이어그램을 생성하여 내부 중심선을 추출합니다.

        Args:
            geom (Any): 병합된 면형 Geometry

        Returns:
            List[LineString]: 추출된 원시 중심선 리스트
        """
        polygons: List[Polygon] = []
        if isinstance(geom, Polygon):
            polygons = [geom]
        elif isinstance(geom, MultiPolygon):
            polygons = list(geom.geoms)
        else:
            return []

        all_lines: List[LineString] = []

        for poly in polygons:
            if poly.is_empty:
                continue

            try:
                densified = poly.segmentize(DENSITY_INTERVAL)
            except Exception as e:
                self._logger.log(f"[Skeleton] 경계 조밀화 실패: {e}", level="WARNING")
                continue

            coords = list(densified.exterior.coords)
            for interior in densified.interiors:
                coords.extend(list(interior.coords))

            if len(coords) < 3:
                continue

            try:
                vor = voronoi_diagram(MultiPoint(coords))
                ridges = [part.boundary for part in getattr(vor, "geoms", [])]
                merged_ridges = unary_union(ridges)
                skeleton_geom = merged_ridges.intersection(poly)

                if isinstance(skeleton_geom, LineString):
                    all_lines.append(skeleton_geom)
                elif isinstance(skeleton_geom, MultiLineString):
                    all_lines.extend(list(skeleton_geom.geoms))
                elif hasattr(skeleton_geom, "geoms"):
                    for g in skeleton_geom.geoms:
                        if isinstance(g, LineString):
                            all_lines.append(g)
            except Exception as e:
                self._logger.log(f"[Skeleton] Voronoi 생성 실패: {e}", level="WARNING")
                continue

        return all_lines