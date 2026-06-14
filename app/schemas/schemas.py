# =============================================================================
# app/schemas/schemas.py
# Pydantic v2 request/response models — the API contract layer
# Completely decoupled from ORM models (intentional — prevents leaking DB internals)
# =============================================================================

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request schemas — what the caller sends in
# ---------------------------------------------------------------------------
class JobCreateRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Human-readable job title",
        examples=["Q3 Financial Report Analysis"]
    )
    raw_text: str = Field(
        ...,
        min_length=10,
        description="Raw document text to parse and index",
        examples=["This is a quarterly financial report covering revenue, expenses, and projections..."]
    )

    @field_validator("raw_text")
    @classmethod
    def no_empty_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_text must contain non-whitespace content.")
        return v.strip()


# ---------------------------------------------------------------------------
# Response schemas — what the API returns
# ---------------------------------------------------------------------------
class EntityResponse(BaseModel):
    entity_type:  str
    entity_key:   str
    entity_value: str
    confidence:   Optional[float] = None

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id:                 uuid.UUID
    title:              str
    status:             str
    document_type:      Optional[str] = None
    processed_summary:  Optional[str] = None
    token_count:        Optional[int] = None
    created_at:         datetime
    entities:           list[EntityResponse] = []

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    total: int
    jobs:  list[JobResponse]


class HealthResponse(BaseModel):
    status:  str
    version: str
    db:      str
