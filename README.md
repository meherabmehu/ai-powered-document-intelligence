# AI-Powered Document Intelligence

A local-first document workflow for extracting, validating, and searching
invoice information across PDFs, scanned images, spreadsheets, and CSV files.
This project was created for the AI Engineer recruitment assessment.

## What works

- Bounded multi-file uploads for PDF, JPG/JPEG, PNG, TIFF, XLSX, XLS, and CSV.
- PDF text extraction with OCR fallback for sparse pages; image OCR and
  multi-sheet spreadsheet parsing.
- Background processing with Celery and Redis, with attempt history, progress,
  failure states, and retry support.
- Conservative local field extraction, optional OpenAI-compatible extraction
  and embeddings, amount/line-item checks, duplicate detection, and related
  document mismatch alerts.
- REST API for upload, status/results, correction, retry, history, and keyword
  or semantic search.
- React review workspace with upload, polling, search, validation issues, and
  editable invoice fields.
- Initial PostgreSQL/pgvector migration is applied automatically at API startup.

## Stack

- **API:** Python 3.11+, FastAPI, SQLAlchemy, Alembic, Celery
- **UI:** React, TypeScript, Vite
- **Storage/search:** PostgreSQL + pgvector, Redis, local upload directory for
  development
- **Extraction:** PyMuPDF, Tesseract OCR, pandas, openpyxl, xlrd
- **Optional AI:** OpenAI-compatible extraction and embedding APIs

## Prerequisites

- Git
- Python 3.11 or newer
- Node.js 20 or newer and npm
- Docker Desktop with Docker Compose
- Tesseract OCR installed and available on `PATH` for scanned-document OCR

## Run locally (PowerShell)

1. Copy `.env.example` to `.env`. The example values are for local development.
   Keep real API keys in `.env`; never commit them.
2. Start PostgreSQL and Redis:

   ```powershell
   docker compose up -d postgres redis
   ```

3. Install backend dependencies and start the API from the repository root:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e "backend[dev]"
   python -m uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000
   ```

   The API runs database migrations at startup. Interactive API documentation
   is at <http://localhost:8000/docs>.

4. In a separate terminal, start the Celery worker. On Windows, use the
   single-process `solo` pool:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   Set-Location backend
   python -m celery -A app.queue:celery_app worker --pool=solo --loglevel=INFO
   ```

5. In another terminal, install and start the frontend:

   ```powershell
   Set-Location frontend
   npm install
   npm run dev
   ```

6. Open <http://localhost:5173>. Vite proxies `/api` requests to the local API.

## AI provider configuration

Extraction works without an external AI account using conservative label-based
patterns. Missing fields remain `null`, and outputs are still subject to
validation and human review. To enable an OpenAI-compatible provider, configure
`LLM_API_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in `.env`. Semantic search
requires an embedding provider configured with `EMBEDDING_API_BASE_URL`,
`EMBEDDING_API_KEY`, and `EMBEDDING_MODEL`; it must return 1536-dimensional
vectors. No provider is configured by default. Do not send private customer
documents to a third party without authorization.

## API outline

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | API process health |
| `POST` | `/api/documents/upload` | Upload up to 10 files (25 MiB per file by default) |
| `GET` | `/api/documents` | List documents with optional status and pagination |
| `GET` | `/api/documents/{id}` | Read document and extracted result |
| `GET` | `/api/documents/{id}/status` | Read processing status and progress |
| `GET` | `/api/documents/{id}/result` | Read result after processing completes |
| `GET` | `/api/documents/{id}/attempts` | Read processing attempt history |
| `PATCH` | `/api/documents/{id}/correction` | Correct invoice fields and rerun validation |
| `POST` | `/api/documents/{id}/retry` | Retry a failed document |
| `GET` | `/api/search?q=...&mode=keyword\|semantic` | Search document text or embeddings |

`MAX_UPLOAD_BYTES`, `MAX_PDF_PAGES`, `UPLOAD_DIR`, `DATABASE_URL`, and
`REDIS_URL` are configurable in `.env`. Uploaded files remain in the local
development storage directory and are not automatically deleted.

## Evaluation and limitations

The assessment does not provide a labeled invoice corpus. Any reported
extraction score must therefore be calculated against clearly labeled,
synthetic fixtures and described as a synthetic baseline—not as real-world
accuracy. OCR quality depends on scan clarity and the locally installed
Tesseract language data. Pattern-based extraction is intentionally
conservative; it is not a replacement for review or a trained invoice model.

The included label-based evaluation can be run with
`python backend/evaluation/evaluate_synthetic.py`. Its current result is 24/24
field matches (100% micro exact match) on only three synthetic, deliberately
well-formed invoices; this is a smoke baseline for the parser and must not be
interpreted as representative accuracy.

This is an assessment/demo implementation, not a production-ready service:
authentication/authorization, malware scanning, managed object storage,
retention controls, rate limiting, and operational monitoring still need to be
added before handling real customer data.

## Quality checks

From the repository root:

```powershell
python -m pytest backend
python -m ruff check backend
Set-Location frontend
npm test
npm run build
npm audit --audit-level=low
```

## Walkthrough checklist

1. Start PostgreSQL, Redis, the API, the Celery worker, and the frontend.
2. Upload a labeled sample invoice and show it move from queued to completed.
3. Open its review panel; compare extracted fields and validation issues with
   the source text.
4. Correct a field and show that the corrected record is revalidated.
5. Search for a supplier or invoice number; explain that semantic search needs
   an explicitly configured embedding provider.
6. Show a failed-file retry and point out that synthetic evaluation is not
   evidence of production accuracy.

## AI-assisted development disclosure

AI assistance was used to interpret the assignment, design, implement, and
test this project. Extracted values are untrusted candidates: validate them and
review uncertain or inconsistent records against the original source. No
private customer documents or secrets belong in source control.
