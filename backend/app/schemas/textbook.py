"""阶段四 schema：教材、扫码结果、照片。"""

from datetime import datetime

from pydantic import BaseModel, Field


class TextbookOut(BaseModel):
    id: str
    isbn: str | None
    title: str
    author: str | None
    publisher: str | None
    edition: str | None
    cover_local_path: str | None

    model_config = {"from_attributes": True}


class TextbookCreate(BaseModel):
    """手动录入（扫码失败兜底）：ISBN 可空，title 必填。"""

    isbn: str | None = Field(default=None, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    publisher: str | None = Field(default=None, max_length=200)
    edition: str | None = Field(default=None, max_length=50)


class ScanResult(BaseModel):
    """单本扫码结果：found=Open Library 命中；exists=书库已有；need_manual=进兜底。"""

    isbn: str
    status: str  # found / exists / need_manual
    textbook: TextbookOut | None = None


class BatchScanResult(BaseModel):
    results: list[ScanResult]


class LocationPhotoOut(BaseModel):
    id: str
    location_name: str
    photo_type: str
    photo_path: str
    created_at: datetime

    model_config = {"from_attributes": True}
