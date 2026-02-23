"""
Service/worker.py

GIS 데이터 처리 파이프라인을 별도 스레드에서 실행하는 작업자 모듈입니다.
"""
import traceback
from PySide6.QtCore import QThread, Signal

from Common.log import Log
from Service.gis_service import GISService
from Function.decorators import log_execution_time


class GISWorker(QThread):
    """
    GIS 파이프라인 작업을 비동기로 수행하는 스레드 클래스입니다.
    """

    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, logger: Log, gis_service: GISService, input_path: str):
        super().__init__()
        self._logger = logger
        self._gis_service = gis_service
        self._input_path = input_path

    @log_execution_time
    def run(self) -> None:
        """
        GIS 파이프라인을 실행하고 결과에 따라 완료 또는 오류 시그널을 송신합니다.
        """
        try:
            result_path = self._gis_service.run_pipeline(self._input_path)
            self.finished_signal.emit(str(result_path))

        except Exception as e:
            err_details = traceback.format_exc()
            self._logger.log(f"GIS 파이프라인 실행 중 오류 발생:\n{err_details}", level="ERROR")
            self.error_signal.emit(str(e))