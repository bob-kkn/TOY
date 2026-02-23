"""
main.py

애플리케이션의 진입점이며 객체 생성 및 의존성 주입(Composition Root)을 담당합니다.
"""
from __future__ import annotations

import Function.knw_license

import signal
import sys
import traceback
from typing import NoReturn

from PySide6.QtWidgets import QApplication

from Common.log import Log
from Function.log_cleanup import clean_old_logs
from Service.container import build_app


def _signal_handler(_sig, _frame) -> None:
    """터미널에서 인터럽트 신호 발생 시 애플리케이션을 안전하게 종료합니다."""
    app = QApplication.instance()
    if app:
        app.quit()


def main() -> NoReturn:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    app = QApplication(sys.argv)
    logger = Log()

    try:
        logger.log("=== 애플리케이션 초기화 시작 ===", level="INFO")

        clean_old_logs(logger.log_dir, logger)

        built = build_app(logger)
        ui_service = built.ui_service

        ui_service.load_main_window()
        ui_service.show()

        logger.log("=== 애플리케이션 실행 준비 완료 ===", level="INFO")

        exit_code = app.exec()

        logger.log(f"=== 애플리케이션 정상 종료 (Exit Code: {exit_code}) ===", level="INFO")
        sys.exit(exit_code)

    except Exception:
        error_msg = traceback.format_exc()
        logger.log(f"초기화 중 치명적 오류 발생:\n{error_msg}", level="ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()