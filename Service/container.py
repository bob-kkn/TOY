"""
Service/container.py

애플리케이션의 모든 객체를 생성하고 의존성을 주입하여 실행 가능한 상태로 조립합니다.
"""
from __future__ import annotations

from dataclasses import dataclass

from Common.log import Log
from Function.setting_manager import SettingManager

from Service.config import GISConfig
from Service.gis_modules import GISIO, ResultValidator, SkeletonProcessor
from Service.gis_modules.topology import (
    TopologyProcessor,
    CoordinateSnapper,
    Planarizer,
    IntersectionMerger,
    TerminalForkCleaner,
    SpurCleaner,
    IntersectionSmoother,
    TopologyCleaner,
    NetworkSimplifier,
    TopologyDiagnostics
)

from Service.gis_service import GISService
from Service.ui_service import UIService


@dataclass(frozen=True)
class BuiltApp:
    """조립이 완료된 애플리케이션 서비스 객체 묶음입니다."""
    ui_service: UIService
    gis_service: GISService


def build_app(logger: Log) -> BuiltApp:
    """
    설정 로드 및 모든 내부 모듈의 의존성을 주입하여 BuiltApp 객체를 생성합니다.
    """
    settings_manager = SettingManager()
    gis_config = GISConfig()

    gis_io = GISIO(logger)

    skeleton_processor = SkeletonProcessor(logger, gis_config)

    snapper = CoordinateSnapper(logger)
    planarizer = Planarizer(logger)
    merger = IntersectionMerger(logger, gis_config)
    fork_cleaner = TerminalForkCleaner(logger)
    spur_cleaner = SpurCleaner(logger)
    smoother = IntersectionSmoother(logger)
    cleaner = TopologyCleaner(logger)
    simplifier = NetworkSimplifier(logger, gis_config)
    diagnostics = TopologyDiagnostics(logger)

    topology_processor = TopologyProcessor(
        logger=logger,
        config=gis_config,
        snapper=snapper,
        planarizer=planarizer,
        merger=merger,
        fork_cleaner=fork_cleaner,
        spur_cleaner=spur_cleaner,
        smoother=smoother,
        cleaner=cleaner,
        simplifier=simplifier,
        diagnostics=diagnostics,
    )

    validator = ResultValidator(logger, gis_config)

    gis_service = GISService(
        logger=logger,
        gis_io=gis_io,
        skeleton_processor=skeleton_processor,
        topology_processor=topology_processor,
        validator=validator,
        config=gis_config,
    )

    ui_service = UIService(
        logger=logger,
        settings=settings_manager,
        gis_service=gis_service,
    )

    return BuiltApp(ui_service=ui_service, gis_service=gis_service)