"""
Function/log_cleanup.py

설정된 보관 기간이 지난 오래된 로그 파일을 자동으로 삭제하는 모듈입니다.
"""
import os
import datetime

RETENTION_DAYS = 3


def clean_old_logs(log_dir, logger):
    """
    지정된 디렉토리 내에서 보관 기간이 만료된 로그 파일을 찾아 삭제합니다.

    Args:
        log_dir (str): 로그 파일이 저장된 디렉토리 경로
        logger (Log): 로그 기록을 위한 로거 인스턴스
    """
    try:
        if not os.path.exists(log_dir):
            logger.log(f"로그 디렉토리 없음: {log_dir} (삭제 과정 생략)", level="WARNING")
            return

        now = datetime.datetime.now()

        for file_name in os.listdir(log_dir):
            file_path = os.path.join(log_dir, file_name)

            if not (os.path.isfile(file_path) and file_name.startswith("Log_")):
                continue

            try:
                date_part = file_name[4:12]

                if not date_part.isdigit():
                    continue

                file_date = datetime.datetime.strptime(date_part, "%Y%m%d")

                if (now - file_date).days > RETENTION_DAYS:
                    os.remove(file_path)
                    logger.log(f"오래된 로그 파일 삭제: {file_name}", level="INFO")

            except ValueError:
                logger.log(f"잘못된 로그 파일 형식 (삭제 스킵): {file_name}", level="WARNING")

    except Exception as e:
        logger.log(f"로그 파일 정리 중 오류 발생: {e} (기능 패스)", level="ERROR")