"""
Function/setting_manager.py

애플리케이션의 설정값(INI)을 관리하는 공통 모듈입니다.
"""

import configparser
from Function.utils import get_runtime_base_path


class SettingManager:
    """
    설정 파일의 읽기, 쓰기 및 변경 사항 저장을 관리하는 클래스입니다.
    """
    def __init__(self, filename="settings.ini"):
        self.config_path = get_runtime_base_path() / filename
        self.config = configparser.ConfigParser()

        if self.config_path.exists():
            try:
                self.config.read(self.config_path, encoding='utf-8')
            except Exception as e:
                print(f"[SettingManager] 설정 파일 읽기 실패: {e}")
                self._save()
        else:
            self._save()

    def get(self, section: str, key: str, fallback: str = "") -> str:
        """
        지정된 섹션과 키에 해당하는 설정값을 반환합니다.

        Args:
            section (str): 설정 섹션명
            key (str): 설정 키값
            fallback (str): 값이 없을 경우 반환할 기본값

        Returns:
            str: 설정값
        """
        try:
            return self.config.get(section, key, fallback=fallback)
        except Exception:
            return fallback

    def set(self, section: str, key: str, value: str):
        """
        메모리상의 설정값을 변경합니다. 실제 반영을 위해서는 save() 호출이 필요합니다.

        Args:
            section (str): 설정 섹션명
            key (str): 설정 키값
            value (str): 저장할 값
        """
        if not self.config.has_section(section):
            self.config.add_section(section)

        self.config.set(section, key, str(value))

    def save(self):
        """현재 메모리의 설정 내용을 파일에 기록합니다."""
        self._save()

    def _save(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.config.write(f)
        except Exception as e:
            print(f"[SettingManager] 설정 파일 저장 실패: {e}")