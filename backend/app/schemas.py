from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentSummary(BaseModel):
    id: str
    original_filename: str
    media_type: str
    size_bytes: int
    status: str
    progress: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDetail(DocumentSummary):
    extracted_text: str | None = None
    extracted_data: dict[str, Any] | None = None
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class CorrectionRequest(BaseModel):
    extracted_data: dict[str, Any]


class AttemptSummary(BaseModel):
    id: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
