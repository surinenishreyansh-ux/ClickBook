# CLICKBOOK — Production Architecture Migration Report

**Date:** 2026-11-21  
**Project:** ClickBook Full-Stack Event Photography Platform  
**Target Architecture:** Cloudflare Pages + Cloudflare R2 + Neon PostgreSQL + Oracle Cloud (OCI) ARM64/AMD64 Docker FastAPI + Google Gemini API + OpenCV YuNet/SFace  

---

## 1. Existing Architecture Audit

### 1.1 Frontend
- **Framework:** React 18 with Vite 5, JavaScript (JSX).
- **Styling:** Custom high-contrast responsive CSS (`styles.css`), Lucide icons, QRCodeCanvas for client-side QR generation.
- **Routing:** Lightweight client-side router (`useRoute` hook relying on `history.pushState` and `popstate` events).
- **API Client:** Standard `fetch` wrapper in `src/api.js` using `VITE_API_BASE_URL` with local storage for auth bearer tokens.
- **Image Delivery:** Direct URL calls to backend `/api/g/{code}/photos/{pid}/image?size={thumb|view|full}`.
- **Real-Time Gallery:** Server-Sent Events (SSE) via `/api/g/{code}/stream` with 18-second periodic polling fallback.
- **Camera Capture:** Web `navigator.mediaDevices.getUserMedia` video stream rendered to canvas for JPEG export.

### 1.2 Backend
- **Framework:** FastAPI (Python 3.12 / 3.14 compatible) with Uvicorn.
- **Database ORM:** SQLAlchemy 2.0 with synchronous `SessionLocal` sessions.
- **Default Database:** SQLite (`backend/data/clickbook.sqlite3`) with WAL journal mode, busy timeouts, and SQLite foreign key pragmas.
- **Storage Layer:** Dual driver (`local` filesystem writing to `DATA / uploads`, or partial `s3` via `boto3`).
- **AI / Biometrics:**
  - OpenCV Zoo YuNet ONNX model (`face_detection_yunet_2023mar.onnx`) for face bounding box detection.
  - OpenCV Zoo SFace ONNX model (`face_recognition_sface_2021dec.onnx`) for 128-dimensional unit-norm face embedding vectors.
  - Custom cosine distance and clustering algorithms (`app/face_ai.py`).
- **Background Processing:** In-process single background worker thread (`_face_worker_loop`) polling SQLite for `face_status=='queued'`. Interrupted jobs reset to `queued` on lifespan start.
- **Security & Auth:**
  - Passwords: Salted `scrypt` hashing (`n=2**14, r=8, p=1`).
  - Sessions: 48-byte URL-safe tokens stored as SHA-256 digests in `sessions` table (14-day validity).
  - Authorization: Role checks (`must_owner`, `must_member`) based on event ownership and team member records.
  - Guest Access: Secret URL guest code token (`guest_code`) isolating photo access per event without guest logins.
  - Biometric Consent: Mandatory consent flags required for selfie searches and face-in-photo searches.

### 1.3 DSLR / Tethering Uploader
- Standalone Python utility (`uploader/clickbook_uploader.py`) requiring zero third-party dependencies.
- Watches local directory for camera tethering JPEGs, verifies file write stabilization, computes SHA-256, and uploads via HTTP multipart to `POST /api/events/{eid}/photos`.
- Maintains local per-event sync state in `.clickbook-upload-state.json`.

---

## 2. Existing Working Functionality (Verified & Tested)

The following core features have been inspected and confirmed passing in baseline automated test suites and live server checks:
1. **User Authentication:** Registration, password hashing, session issuance, `GET /api/auth/me`, logout token revocation.
2. **Event Lifecycle:** Creation with unlisted guest codes, role assignment, event metadata updates, QR code rotation, cascade deletion.
3. **Team Management:** 7-day single-use invitation tokens, optional email restrictions, acceptance flow, photographer revocation.
4. **Photo Ingestion:** Multi-resolution JPEG normalization (4000px full, 1600px view, 650px thumbnail), SHA-256 deduplication per event.
5. **Guest Gallery:** Live streaming via SSE, responsive photo grid, full-resolution download permissions toggling.
6. **Face Biometrics:**
   - YuNet ONNX detection + SFace ONNX feature extraction (models installed and operational).
   - Clustering of matching attendees by cosine threshold.
   - Consent-gated selfie search (ephemeral in-memory vector comparison; selfies are never persisted to disk or DB).
   - Interactive face bounding box selection in event photos.
7. **DSLR Sync Tool:** Compatible folder monitor with write stabilization and automated upload retry.

---

## 3. Required Changes for Target Architecture

### 3.1 Database: Neon PostgreSQL & Alembic
- **Connection Configuration:**
  - Standardize `DATABASE_URL` supporting `postgresql+psycopg://`.
  - Implement connection pooling (`QueuePool`, `pool_size`, `max_overflow`, `pool_recycle`, `pool_pre_ping`).
  - Support SSL connection parameters (`sslmode=require`) essential for Neon.
  - Implement retry/reconnect resilience for Neon auto-suspend / cold-start resume.
  - Preserve SQLite engine fallback for offline local testing and lightweight development.
- **Alembic Migrations:**
  - Create `alembic.ini` and `migrations/` directory with `env.py` configured for models in `app/db.py`.
  - Initial baseline migration capturing all existing tables: `users`, `sessions`, `events`, `members`, `invites`, `photos`, `faces`.
  - Add tables/columns for:
    - Persistent job queue (`jobs` table).
    - Gemini semantic metadata on `photos` table (`gemini_description`, `gemini_context`, `gemini_moment_type`, `gemini_tags`, `gemini_caption`, `gemini_status`).

### 3.2 Storage: Cloudflare R2 S3-Compatible Adapter
- **Environment Variables:** `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_ENDPOINT_URL`, `R2_PUBLIC_BASE_URL`.
- **R2 Storage Adapter:**
  - S3-compatible client with AWS SigV4 addressing via `boto3`.
  - Presigned upload URL generation (`generate_presigned_url('put_object', ...)`).
  - Presigned download URL generation (`generate_presigned_url('get_object', ...)` with 15-minute expiration and Content-Disposition headers).
  - Upload verification (`head_object`) before confirming records in PostgreSQL.
  - Direct R2 upload flow:
    1. Client requests presigned upload authorization from FastAPI (`POST /api/events/{eid}/photos/request-upload`).
    2. Client uploads directly to Cloudflare R2 bucket.
    3. Client notifies FastAPI to verify and register photo (`POST /api/events/{eid}/photos/confirm-upload`).
    4. FastAPI verifies object presence, reads dimensions/thumbnails, registers database record, and queues AI job.
  - Backward Compatibility: Keep existing direct multipart upload endpoint (`POST /api/events/{eid}/photos`) functioning for the DSLR auto-uploader (`clickbook_uploader.py`).
  - Dual-mode support: Seamless fallback to local storage driver when R2 credentials are not set.

### 3.3 Semantic AI: Google Gemini API Integration
- **SDK:** Official `google-genai` Python library.
- **Model:** Supported modern multimodal vision model (e.g. `gemini-2.5-flash` or `gemini-1.5-flash`).
- **Functionality:**
  - Image description, event context classification (ceremony, reception, candid, performance, portraits).
  - Searchable semantic tags and contextual captions.
  - Search API (`GET /api/events/{eid}/photos/search?q=...` and guest gallery search `GET /api/g/{code}/photos/search?q=...`).
- **Privacy & Safety Constraints:**
  - Never transmit guest selfies or face embeddings to Gemini.
  - Process only event photos after organizer upload.
  - Optional: If `GEMINI_API_KEY` is not provided, the application runs normally with Gemini features cleanly bypassed.

### 3.4 Persistent Background Job Queue
- **Problem with Current Queue:** Single in-process Python thread scanning SQLite rows, prone to race conditions across multiple worker processes or restarts.
- **Solution:** PostgreSQL-backed persistent task queue with atomic state transitions (`pending`, `processing`, `completed`, `failed`), lease expirations, max retry attempts, and exponential backoff.
- **Decoupled Architecture:** Clean job processor interface that can run embedded or as a standalone background worker container, easily adaptable to Redis/Celery in high-throughput deployments.

### 3.5 Cloudflare Pages Frontend Deployment
- SPA redirect rule (`_redirects` file: `/* /index.html 200`).
- Environment variable `VITE_API_BASE_URL` pointing to the OCI FastAPI backend URL.
- Production CORS configuration in FastAPI accepting the Cloudflare Pages origin.

### 3.6 Oracle Cloud Infrastructure (OCI) Deployment
- **Architecture:** ARM64 (Ampere A1) and AMD64 compatible multi-stage Docker build.
- **Reverse Proxy:** Production Caddy / Nginx reverse proxy configuration with automatic HTTPS Let's Encrypt certificates.
- **Security:** Model weights downloaded at build time, non-root execution, healthchecks, and host firewall configuration.

---

## 4. Potential Breaking Changes & Mitigations

| Area | Potential Risk | Mitigation |
|---|---|---|
| **Database Engines** | Incompatible SQL dialects, case sensitivity, or type differences between SQLite and Postgres. | Use SQLAlchemy abstract types (`String`, `DateTime(timezone=True)`, `JSON`). Validate migrations with Alembic on both SQLite and PostgreSQL. |
| **Photo Uploads** | Switching exclusively to R2 presigned URLs would break the existing DSLR desktop uploader. | Maintain dual upload endpoints: direct multipart upload for DSLR uploader/legacy clients, plus presigned upload endpoints for browser frontend. |
| **Guest Gallery Images** | Serving images from private R2 buckets requires either presigned redirect URLs or backend streaming. | Support transparent 302 redirects to time-limited presigned R2 URLs, or backend streaming proxy fallback when running locally. |
| **Gemini Quota Limits** | API rate limits or network failures during batch photo processing. | Exponential backoff retries in job queue; record errors in DB without blocking face indexing or gallery availability. |
| **Neon Cold Starts** | Serverless compute suspension causing connection timeouts on first incoming query. | Configure SQLAlchemy connection pool with `pool_pre_ping=True`, `pool_recycle=300`, and automatic reconnect attempts. |

---

## 5. Deployment Requirements

1. **Neon PostgreSQL:**
   - Database connection string (`DATABASE_URL=postgresql+psycopg://...sslmode=require`).
2. **Cloudflare:**
   - Cloudflare R2 bucket with S3 API tokens.
   - Cloudflare Pages project pointing to `frontend/dist`.
   - Custom domains with Cloudflare DNS proxying.
3. **Google Gemini:**
   - API key from Google AI Studio (`GEMINI_API_KEY`).
4. **Oracle Cloud Infrastructure (OCI):**
   - 1x Ampere A1 Compute Instance (Ubuntu 24.04 ARM64, 2–4 OCPU, 12–24 GB RAM within Free Tier).
   - Ingress security rules opening ports 80 and 443.
   - Docker and Docker Compose installed.

---

## 6. Security & Biometric Compliance Review

1. **Biometric Privacy:** YuNet and SFace embeddings are stored strictly as 128D vectors in Postgres. Face matching is event-scoped and consent-gated. Ephemeral guest selfies are never persisted to disk or S3.
2. **Private Storage:** Cloudflare R2 buckets remain private. Direct public bucket access is disabled; all client access is governed by 15-minute presigned URLs or authenticated endpoints.
3. **Credential Isolation:** R2 keys, Gemini API keys, and database passwords reside exclusively in environment variables and are never bundled into frontend assets or git commits.
4. **Session Security:** Cryptographic password hashing (`scrypt`), timing-attack safe token comparison (`hmac.compare_digest`), SHA-256 hashed session tokens, and strict CORS policies.
