# =============================================================================
# app/services/services.py
# Service layer — orchestrates LlamaIndex document parsing and DB persistence
#
# Architecture pattern: Thin API routes → Fat service layer → Thin DB models
# This keeps business logic testable without HTTP context
# =============================================================================

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# LlamaIndex core primitives — minimal surface area, production-safe
from llama_index.core import Document, VectorStoreIndex, Settings as LlamaSettings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.llms.openai import OpenAI as LlamaOpenAI

from app.core.config import settings
from app.models.models import WorkflowJob, ParsedEntity, JobStatus, DocumentType
from app.schemas.schemas import JobCreateRequest, JobResponse, EntityResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LlamaIndex bootstrap — configure once at module load, not per-request
# Using the Settings singleton pattern (replaces deprecated ServiceContext)
# ---------------------------------------------------------------------------
def _bootstrap_llama() -> None:
    """
    Wire the LLM and node parser into LlamaIndex's global Settings object.
    In production you'd swap MockLLM for LlamaOpenAI when OPENAI_API_KEY is real.
    """
    try:
        # Attempt real OpenAI — falls through to mock if key is placeholder
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "sk-placeholder":
            LlamaSettings.llm = LlamaOpenAI(
                model="gpt-3.5-turbo",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.0,
            )
            logger.info("LlamaIndex: OpenAI LLM configured.")
        else:
            # MockLLM — zero cost, works offline, perfect for dev/CI
            from llama_index.core.llms import MockLLM
            LlamaSettings.llm = MockLLM(max_tokens=256)
            logger.warning("LlamaIndex: MockLLM active — set OPENAI_API_KEY for real inference.")

        # SentenceSplitter: chunks text into overlapping nodes for indexing
        LlamaSettings.node_parser = SentenceSplitter(
            chunk_size=512,
            chunk_overlap=64,
        )
        logger.info("LlamaIndex bootstrap complete.")
    except Exception as exc:
        logger.error(f"LlamaIndex bootstrap failed: {exc}")
        raise


_bootstrap_llama()


# ---------------------------------------------------------------------------
# Core parsing function — LlamaIndex document → structured entity list
# ---------------------------------------------------------------------------
async def parse_document_with_llama(raw_text: str) -> dict:
    """
    Wraps raw text in a LlamaIndex Document, runs node parsing,
    and extracts structured metadata fields.

    Returns a dict with:
      - summary:        str   — condensed representation of the document
      - token_count:    int   — total token approximation across all nodes
      - entities:       list  — extracted key/value entities with confidence
      - document_type:  str   — classified document category
    """
    try:
        # Step 1 — wrap raw text in a Document object with metadata
        document = Document(
            text=raw_text,
            metadata={
                "source": "api_submission",
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Step 2 — split document into nodes (sentences/paragraphs)
        node_parser = LlamaSettings.node_parser
        nodes = node_parser.get_nodes_from_documents([document])

        # Step 3 — aggregate token counts across all parsed nodes
        total_tokens = sum(len(node.text.split()) for node in nodes)

        # Step 4 — build entity list from node text (keyword extraction)
        #          In production: swap this loop with a real NLP pipeline
        entities = []
        for i, node in enumerate(nodes[:10]):   # cap at 10 nodes for demo
            words = [w.strip(".,!?;:") for w in node.text.split() if len(w) > 5]
            unique_keywords = list(dict.fromkeys(words))[:5]

            for kw in unique_keywords:
                entities.append({
                    "entity_type":  "KEYWORD",
                    "entity_key":   f"node_{i}_keyword",
                    "entity_value": kw,
                    "confidence":   round(0.7 + (len(kw) % 3) * 0.1, 2),  # deterministic mock score
                })

        # Step 5 — classify document type from content heuristics
        doc_type = _classify_document(raw_text)

        # Step 6 — generate a summary (real LLM uses query engine; mock = truncation)
        summary = _generate_summary(raw_text, nodes)

        return {
            "summary":       summary,
            "token_count":   total_tokens,
            "entities":      entities,
            "document_type": doc_type,
        }

    except Exception as exc:
        logger.error(f"LlamaIndex parse error: {exc}")
        raise


def _classify_document(text: str) -> DocumentType:
    """Lightweight heuristic classifier — replace with an ML model in production."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["invoice", "total", "payment", "amount"]):
        return DocumentType.STRUCTURED
    if any(kw in text_lower for kw in ["report", "analysis", "summary", "overview"]):
        return DocumentType.MIXED
    return DocumentType.RAW_TEXT


def _generate_summary(text: str, nodes) -> str:
    """Returns first 300 chars as summary when MockLLM is active."""
    if len(nodes) == 0:
        return "No content parsed."
    # With a real LLM, you'd call: index.as_query_engine().query("Summarize...")
    return text[:300].strip() + ("..." if len(text) > 300 else "")


# ---------------------------------------------------------------------------
# WorkflowJobService — CRUD + orchestration bound to a DB session
# ---------------------------------------------------------------------------
class WorkflowJobService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Create & process a new job ──────────────────────────────────────────
    async def create_and_process_job(self, payload: JobCreateRequest) -> JobResponse:
        """
        Full pipeline:
          1. Persist job as PENDING
          2. Parse with LlamaIndex
          3. Persist parsed entities
          4. Update job status to COMPLETED | FAILED
        """
        # --- 1. Create PENDING job record ---
        job = WorkflowJob(
            title=payload.title,
            raw_input=payload.raw_text,
            status=JobStatus.PENDING,
        )
        self.db.add(job)
        await self.db.flush()          # flush to get generated UUID without full commit
        logger.info(f"Job created: {job.id}")

        # --- 2. Transition to PROCESSING ---
        job.status = JobStatus.PROCESSING
        await self.db.flush()

        try:
            # --- 3. LlamaIndex parse ---
            result = await parse_document_with_llama(payload.raw_text)

            # --- 4. Update job with parsed results ---
            job.processed_summary = result["summary"]
            job.token_count       = result["token_count"]
            job.document_type     = result["document_type"]
            job.status            = JobStatus.COMPLETED

            # --- 5. Bulk insert parsed entities ---
            entity_objects = [
                ParsedEntity(
                    job_id=job.id,
                    entity_type=e["entity_type"],
                    entity_key=e["entity_key"],
                    entity_value=e["entity_value"],
                    confidence=e["confidence"],
                )
                for e in result["entities"]
            ]
            self.db.add_all(entity_objects)
            logger.info(f"Job {job.id} completed. Entities extracted: {len(entity_objects)}")

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.processed_summary = f"Processing failed: {str(exc)}"
            logger.error(f"Job {job.id} failed: {exc}")

        await self.db.flush()
        return self._to_response(job)

    # ── Fetch single job by ID ──────────────────────────────────────────────
    async def get_job(self, job_id: uuid.UUID) -> Optional[JobResponse]:
        result = await self.db.execute(
            select(WorkflowJob).where(WorkflowJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        return self._to_response(job) if job else None

    # ── List all jobs (paginated) ───────────────────────────────────────────
    async def list_jobs(self, skip: int = 0, limit: int = 20) -> list[JobResponse]:
        result = await self.db.execute(
            select(WorkflowJob)
            .order_by(WorkflowJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        jobs = result.scalars().all()
        return [self._to_response(j) for j in jobs]

    # ── Serialise ORM model → Pydantic response ─────────────────────────────
    @staticmethod
    def _to_response(job: WorkflowJob) -> JobResponse:
        return JobResponse(
            id=job.id,
            title=job.title,
            status=job.status,
            document_type=job.document_type,
            processed_summary=job.processed_summary,
            token_count=job.token_count,
            created_at=job.created_at,
            entities=[
                EntityResponse(
                    entity_type=e.entity_type,
                    entity_key=e.entity_key,
                    entity_value=e.entity_value,
                    confidence=e.confidence,
                )
                for e in (job.entities or [])
            ],
        )
