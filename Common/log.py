import logging
import datetime
import shutil
import os
import sys


class Log:
    def __init__(self, log_dir="Log"):
        # 프로그램 실행 폴더
        if getattr(sys, 'frozen', False):
            program_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            program_dir = os.path.dirname(os.path.abspath(__file__))

        self.log_dir = os.path.join(program_dir, log_dir)
        os.makedirs(self.log_dir, exist_ok=True) # 디렉토리가 없으면 생성

        # 로그 파일 경로 설정 (파일명은 'Log_YYYYMMDD.log' 형식)
        self.log_file = os.path.join(self.log_dir, f'Log_{self._current_date_str()}.log')
        # 로그 파일 복사 대상 경로 설정 (파일명은 'YYYYMMDD_작업로그.log' 형식)
        self.target_path = os.path.join(program_dir, f'{self._current_date_str()}_작업로그.log')

        # 로그 설정 (로그 파일에 기록, 로그 레벨: DEBUG, 날짜 형식 및 메시지 포맷 설정)
        logging.basicConfig(
            filename=self.log_file,
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y/%m/%d %H:%M',
            encoding='utf-8'
        )

    def _current_date_str(self):
        # 현재 날짜를 'YYYYMMDD' 형식으로 반환하는 메서드
        return datetime.datetime.now().strftime("%Y%m%d")

    def log(self, msg, level='DEBUG', create_log=False):
        """지정된 로그 레벨로 메시지를 기록하고, 필요시 로그 파일을 복사합니다."""
        level = level.upper()  # 로그 레벨을 대문자로 변환
        if level == "ERROR":
            logging.error(msg)  # 에러 레벨 로그 기록
        elif level == "INFO":
            logging.info(msg)  # 정보 레벨 로그 기록
        elif level == "WARNING":
            logging.warning(msg)  # 경고 레벨 로그 기록
        elif level == "DEBUG":
            logging.debug(msg)  # 디버그 레벨 로그 기록
        else:
            print(f"알 수 없는 로그 레벨: {level}")
            return  # 알 수 없는 로그 레벨인 경우 반환

        print(f"{level}: {msg}")  # 콘솔에 로그 출력

        # 로그 파일을 복사할지 여부 (기본값: True)
        if create_log:
            self._copy_log()  # 로그 파일 복사 시도

    def _copy_log(self):
        """로그 파일을 지정된 경로로 복사하는 메서드."""
        try:
            shutil.copy(self.log_file, self.target_path)  # 로그 파일 복사
        except Exception as e:
            print(f"로그 파일 복사 실패: {e}")  # 복사 실패 시 오류 메시지 출력

    def get_log_paths(self):
        """현재 로그 파일 경로를 반환하는 메서드."""
        return self.log_file
