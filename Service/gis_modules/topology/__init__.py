"""
Service/gis_modules/topology/__init__.py

중심선의 위상 구조를 정규화하고 교차로를 최적화하는 토폴로지 관련 모듈들을 외부로 노출합니다.
"""
from .processor import TopologyProcessor
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

__all__ = [
    "TopologyProcessor",
    "CoordinateSnapper",
    "Planarizer",
    "IntersectionMerger",
    "TerminalForkCleaner",
    "SpurCleaner",
    "IntersectionSmoother",
    "TopologyCleaner",
    "NetworkSimplifier",
    "TopologyDiagnostics",
]