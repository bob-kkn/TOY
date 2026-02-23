"""
Function/decorators.py

함수의 실행 시간 측정 및 예외 처리를 위한 데코레이터 모듈입니다.
"""
from __future__ import annotations

import functools
import logging
import time
import traceback
from typing import Any, Callable, ParamSpec, TypeVar, Optional

P = ParamSpec("P")
R = TypeVar("R")


def _resolve_custom_logger(instance: Any) -> Optional[Any]:
    """
    인스턴스 내부에서 커스텀 로거 메서드 보유 여부를 확인하여 반환합니다.

    Args:
        instance (Any): 클래스 인스턴스(self)

    Returns:
        Optional[Any]: 로거 인스턴스 또는 None
    """
    if instance is None:
        return None

    if hasattr(instance, "_logger") and hasattr(getattr(instance, "_logger"), "log"):
        return getattr(instance, "_logger")

    if hasattr(instance, "logger") and hasattr(getattr(instance, "logger"), "log"):
        return getattr(instance, "logger")

    return None


def log_execution_time(func: Callable[P, R]) -> Callable[P, R]:
    """
    함수의 시작과 종료 시점을 기록하고 실행 시간을 측정하는 데코레이터입니다.

    Returns:
        Callable: 데코레이트된 함수
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        instance = args[0] if args else None
        custom_logger = _resolve_custom_logger(instance)

        func_name = func.__qualname__
        start_time = time.time()

        if custom_logger:
            custom_logger.log(f"▶ [시작] {func_name}", level="DEBUG")
        else:
            logging.debug("▶ [시작] %s", func_name)

        result = func(*args, **kwargs)

        elapsed = time.time() - start_time
        msg = f"◀ [완료] {func_name} (소요 시간: {elapsed:.4f}초)"

        if custom_logger:
            custom_logger.log(msg, level="INFO")
        else:
            logging.info(msg)

        return result

    return wrapper


def safe_run(func: Callable[P, R]) -> Callable[P, R]:
    """
    함수 실행 중 발생하는 예외의 Traceback을 로그에 기록하고 예외를 재전파합니다.

    Returns:
        Callable: 데코레이트된 함수

    Raises:
        Exception: 원본 함수에서 발생한 예외
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        instance = args[0] if args else None
        custom_logger = _resolve_custom_logger(instance)

        try:
            return func(*args, **kwargs)
        except Exception:
            func_name = func.__qualname__
            tb_str = traceback.format_exc()
            log_msg = f"'{func_name}' 실행 중 치명적 오류 발생\n[Traceback]\n{tb_str}"

            if custom_logger:
                custom_logger.log(log_msg, level="ERROR")
            else:
                logging.error(log_msg)

            raise

    return wrapper