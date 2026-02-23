"""
Function/utils.py

프로그램 실행 환경에 따른 파일 및 디렉토리 경로 연산을 처리하는 유틸리티 모듈입니다.
"""
from pathlib import Path
import sys

def get_resource_root_path() -> Path:
    """
    애플리케이션에 포함된 리소스(UI, 아이콘 등)의 루트 경로를 반환합니다.

    Returns:
        Path: 실행 환경(번들형 또는 스크립트형)에 따른 리소스 루트 경로
    """
    return Path(getattr(sys, "_MEIPASS", None) or Path.cwd())

def get_runtime_base_path() -> Path:
    """
    실행 파일 또는 메인 스크립트가 위치한 물리적 경로를 반환합니다.

    Returns:
        Path: 프로그램 실행 파일이 위치한 디렉토리 경로
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent