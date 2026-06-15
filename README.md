# Enterprise Workflow Optimization & Document Automation Suite

An async backend system for document ingestion, automated parsing, and workflow tracking — built with FastAPI, PostgreSQL, and LlamaIndex, fully containerized with Docker.

## Features

- Async REST API built with FastAPI and SQLAlchemy 2.0
- PostgreSQL database with relational job/entity tracking (1-to-many)
- Automated document parsing and keyword/entity extraction using LlamaIndex
- Dockerized multi-service architecture (FastAPI + PostgreSQL + Nginx reverse proxy)
- Health-checked containers with proper startup dependency ordering

## Tech Stack

Python, FastAPI, PostgreSQL, SQLAlchemy (Async), LlamaIndex, Docker, Docker Compose, Nginx

## How to Run

\`\`\`bash
cp .env.example .env
docker compose up -d --build
\`\`\`

API will be available at `http://localhost`. Health check: `http://localhost/health`

## API Endpoints

- `POST /api/v1/jobs` — Submit a document for parsing and tracking
- `GET /api/v1/jobs` — List all processed jobs
- `GET /api/v1/jobs/{id}` — Get a specific job with extracted entities
- `GET /health` — Health check (verifies DB connectivity)

## Example Request

\`\`\`bash
curl -X POST http://localhost/api/v1/jobs \\
  -H "Content-Type: application/json" \\
  -d '{"title":"Sample Job","raw_text":"Your document text here."}'
\`\`\`
