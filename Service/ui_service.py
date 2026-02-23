"""
Service/ui_service.py

사용자 인터페이스와 상호작용을 관리하는 서비스 모듈입니다.
"""
import sys
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox, QMainWindow
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QIODevice
from PySide6.QtGui import QIcon

from Function.utils import get_resource_root_path
from Function.setting_manager import SettingManager
from Common.log import Log
from Service.gis_service import GISService
from Service.worker import GISWorker


class UIService:
    """
    메인 윈도우 UI를 로드하고 이벤트를 처리하는 클래스입니다.
    """

    def __init__(
            self,
            logger: Log,
            settings: SettingManager,
            gis_service: GISService
    ):
        self._logger = logger
        self._settings = settings
        self._gis_service = gis_service

        self._main_window: QMainWindow = None
        self._worker: GISWorker = None

    def load_main_window(self) -> None:
        """
        UI 파일(.ui)을 로드하고 초기 설정을 수행합니다.
        """
        loader = QUiLoader()
        ui_path = get_resource_root_path() / "Res" / "main_window.ui"

        if not ui_path.exists():
            self._logger.log(f"UI 파일을 찾을 수 없습니다: {ui_path}", level="ERROR")
            sys.exit(1)

        ui_file = QFile(str(ui_path))
        if not ui_file.open(QIODevice.ReadOnly):
            self._logger.log(f"UI 파일을 열 수 없습니다: {ui_file.errorString()}", level="ERROR")
            sys.exit(1)

        self._main_window = loader.load(ui_file)
        ui_file.close()

        icon_path = get_resource_root_path() / "Res" / "icon.ico"
        if icon_path.exists():
            self._main_window.setWindowIcon(QIcon(str(icon_path)))

        self._connect_signals()

        self._logger.log("메인 윈도우 UI 로드 성공", level="INFO")

    def show(self) -> None:
        """메인 윈도우 화면을 표시합니다."""
        if self._main_window:
            self._main_window.show()

    def _connect_signals(self) -> None:
        """UI 위젯의 이벤트 시그널을 슬롯 함수에 연결합니다."""
        self._main_window.btn_select_file.clicked.connect(self._open_file_dialog)
        self._main_window.btn_start.clicked.connect(self._handle_start_button)

    def _open_file_dialog(self) -> None:
        """파일 탐색기를 통해 입력 데이터를 선택하고 최근 경로를 저장합니다."""
        last_dir = self._settings.get("PATH", "last_open_dir", fallback=str(Path.home()))

        file_path, _ = QFileDialog.getOpenFileName(
            self._main_window,
            "도로 면형(Polygon) 데이터 선택",
            last_dir,
            "Shapefiles (*.shp);;All Files (*)"
        )

        if file_path:
            self._main_window.le_file_path.setText(file_path)
            self._logger.log(f"파일 선택됨: {file_path}", level="INFO")

            current_dir = str(Path(file_path).parent)
            self._settings.set("PATH", "last_open_dir", current_dir)
            self._settings.save()

    def _handle_start_button(self) -> None:
        """
        작업 시작을 처리하며, 비동기 처리를 위한 워커 스레드를 실행합니다.
        """
        input_path = self._main_window.le_file_path.text()

        if not input_path:
            QMessageBox.warning(self._main_window, "경고", "데이터 파일을 먼저 선택해주세요.")
            return

        self._logger.log(f"작업 요청: {input_path}", level="INFO")

        self._main_window.lbl_status.setText("데이터 처리 중... (잠시만 기다려주세요)")
        self._main_window.btn_start.setEnabled(False)

        # 프로그레스 바를 결정되지 않은 상태의 애니메이션 모드로 전환합니다.
        self._main_window.progress_bar.setRange(0, 0)

        self._worker = GISWorker(self._logger, self._gis_service, input_path)

        self._worker.finished_signal.connect(self._on_process_finished)
        self._worker.error_signal.connect(self._on_process_error)
        self._worker.finished.connect(self._worker.deleteLater)

        self._worker.start()

    def _on_process_finished(self, result_path: str) -> None:
        """
        백그라운드 작업 완료 시 UI 상태를 갱신하고 알림창을 표시합니다.
        """
        self._main_window.lbl_status.setText("작업 완료")

        self._main_window.progress_bar.setRange(0, 100)
        self._main_window.progress_bar.setValue(100)

        self._main_window.btn_start.setEnabled(True)

        QMessageBox.information(
            self._main_window,
            "성공",
            f"작업이 완료되었습니다!\n\n저장 경로:\n{result_path}"
        )
        self._worker = None

    def _on_process_error(self, error_msg: str) -> None:
        """
        백그라운드 작업 중 오류 발생 시 UI 상태를 초기화하고 에러 메시지를 표시합니다.
        """
        self._main_window.lbl_status.setText("오류 발생")

        self._main_window.progress_bar.setRange(0, 100)
        self._main_window.progress_bar.setValue(0)

        self._main_window.btn_start.setEnabled(True)

        QMessageBox.critical(
            self._main_window,
            "실패",
            f"작업 중 오류가 발생했습니다.\n{error_msg}"
        )
        self._worker = None