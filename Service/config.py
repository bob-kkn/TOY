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

    model_config = SettingsConfigDict(
        env_prefix="GIS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )