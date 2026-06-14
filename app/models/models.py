# =============================================================================
# app/models/models.py
# SQLAlchemy ORM — two relational tables:
#   WorkflowJob  → top-level job record (one per API submission)
#   ParsedEntity → extracted fields from the LlamaIndex parsing step
# Relationship: one WorkflowJob has many ParsedEntities (1-to-many)
# =============================================================================

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, DateTime, Enum, ForeignKey,
    Integer, String, Text, Float, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums — stored as native Postgres ENUM types (efficient, self-documenting)
# ---------------------------------------------------------------------------
class JobStatus(str, PyEnum):
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"


class DocumentType(str, PyEnum):
    RAW_TEXT   = "RAW_TEXT"
    STRUCTURED = "STRUCTURED"
    MIXED      = "MIXED"


# ---------------------------------------------------------------------------
# WorkflowJob — primary job tracking table
# ---------------------------------------------------------------------------
class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"

    # Primary key: UUID avoids sequential enumeration attacks in APIs
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )

    # Human-readable job title submitted by the caller
    title = Column(String(255), nullable=False)

    # Raw input payload stored for audit / reprocessing
    raw_input = Column(Text, nullable=False)

    # LlamaIndex summary/output — populated after processing step
    processed_summary = Column(Text, nullable=True)

    # Document classification resolved during parse
    document_type = Column(
        Enum(DocumentType),
        nullable=False,
        default=DocumentType.RAW_TEXT
    )

    # Lifecycle status — PENDING → PROCESSING → COMPLETED | FAILED
    status = Column(
        Enum(JobStatus),
        nullable=False,
        default=JobStatus.PENDING,
        index=True             # filter by status is a hot query path
    )

    # LlamaIndex node/token counts for observability
    token_count = Column(Integer, nullable=True)

    # ISO 8601 UTC timestamps — timezone-aware, never naive datetimes
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship — lazy="selectin" loads children in the same async query
    entities = relationship(
        "ParsedEntity",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # Composite index for the most common dashboard query pattern
    __table_args__ = (
        Index("ix_workflow_jobs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowJob id={self.id} status={self.status}>"


# ---------------------------------------------------------------------------
# ParsedEntity — child table, one row per key/value extracted by LlamaIndex
# ---------------------------------------------------------------------------
class ParsedEntity(Base):
    __tablename__ = "parsed_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key back to parent job — CASCADE DELETE keeps DB clean
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Entity metadata fields populated by the service layer
    entity_type  = Column(String(100), nullable=False)   # e.g. "KEYWORD", "DATE", "PERSON"
    entity_key   = Column(String(255), nullable=False)   # normalised label
    entity_value = Column(Text,        nullable=False)   # extracted value
    confidence   = Column(Float,       nullable=True)    # 0.0–1.0 from LlamaIndex node score

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Back-reference to parent job ORM object
    job = relationship("WorkflowJob", back_populates="entities")

    def __repr__(self) -> str:
        return f"<ParsedEntity job_id={self.job_id} key={self.entity_key}>"
