"""
Service/config.py

GIS 파이프라인의 동작을 제어하는 설정 모듈입니다.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GISConfig(BaseSettings):
    """
    GIS 파이프라인의 핵심 파라미터를 정의하는 설정 클래스입니다.
    """

    debug_export_intermediate: bool = Field(
        default=False,
        description="디버그 모드: 단계별 중간 산출물을 Result 폴더에 저장 여부"
    )

    topology_intersection_merge_threshold_m: float = Field(
        default=1.5,
        ge=0.0,
        description="교차로 단거리 브리지 병합 거리 임계값(m)"
    )

    topology_intersection_parallel_angle_deg: float = Field(
        default=15.0,
        ge=0.0,
        le=90.0,
        description="병렬 진행선 보존을 위한 허용 각도 편차(도)"
    )

    topology_simplify_main_tolerance_m: float = Field(
        default=0.05,
        ge=0.0,
        description="본선 구간 단순화 허용 오차(m)"
    )

    topology_simplify_junction_tolerance_m: float = Field(
        default=0.12,
        ge=0.0,
        description="교차로 접근 구간 단순화 허용 오차(m)"
    )

    topology_junction_min_degree: int = Field(
        default=3,
        ge=2,
        description="교차로 노드로 간주할 최소 차수"
    )

    model_config = SettingsConfigDict(
        env_prefix="GIS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
