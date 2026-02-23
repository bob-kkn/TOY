"""
Service/gis_modules/skeleton/__init__.py

면형 데이터로부터 원시 뼈대를 추출하는 SkeletonProcessor 모듈을 외부로 노출합니다.
"""
from .processor import SkeletonProcessor

__all__ = ["SkeletonProcessor"]