"""
Service/schemas.py

데이터의 구조를 정의하고 입력값의 유효성을 검증하는 스키마 모듈입니다.
"""
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

class FileLoadRequest(BaseModel):
    """
    파일 로드 요청을 위한 데이터 모델입니다.
    """
    file_path: Path = Field(..., description="읽어올 SHP 파일의 경로")

    @field_validator("file_path")
    @classmethod
    def validate_extension(cls, v: Path) -> Path:
        if v.suffix.lower() != ".shp":
            raise ValueError(f"지원하지 않는 파일 형식입니다. (.shp 필요): {v.suffix}")
        return v

    @field_validator("file_path")
    @classmethod
    def validate_existence(cls, v: Path) -> Path:
        resolved_path = v.resolve()
        if not resolved_path.exists() or not resolved_path.is_file():
            raise ValueError(f"파일을 찾을 수 없습니다: {resolved_path}")
        return resolved_path


class FileSaveRequest(BaseModel):
    """
    파일 저장 요청을 위한 데이터 모델입니다.
    """
    output_path: Path = Field(..., description="결과를 저장할 파일 경로")

    @field_validator("output_path")
    @classmethod
    def validate_extension(cls, v: Path) -> Path:
        if v.suffix.lower() != ".shp":
            raise ValueError(f"저장 파일 형식은 .shp여야 합니다: {v.suffix}")
        return v.resolve()