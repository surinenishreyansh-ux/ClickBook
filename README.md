# CLICKBOOK.

**Capture it. Share it. Find it.** Clickbook is a full-stack event-photo platform with owner and photographer accounts, phone camera capture, folder-synced DSLR uploads, live guest galleries, locally run AI face matching, and Google Gemini semantic image understanding.

---

## Target Production Architecture ($0/Month Free Tier)

| Component | Technology | Free Tier Provider |
|---|---|---|
| **Frontend** | React 18, Vite 5, Lucide Icons, QR Canvas | Cloudflare Pages (Free unlimited bandwidth & requests) |
| **Edge & CDN** | DNS, SSL/TLS, Caching | Cloudflare |
| **Backend API** | Python 3.12, FastAPI, Uvicorn | Oracle Cloud Always Free (Ampere A1 ARM64, 4 OCPU, 24 GB RAM) |
| **Reverse Proxy** | Caddy (Automatic HTTPS Let's Encrypt) / Nginx | Docker on Oracle Cloud VM |
| **Database** | PostgreSQL 16, SQLAlchemy, Alembic Migrations | Neon Serverless PostgreSQL (Free Tier) |
| **Photo Storage** | S3-Compatible Private Bucket, Presigned URLs | Cloudflare R2 (10 GB free, $0 egress fees) |
| **Face Biometrics** | YuNet Face Detection + SFace 128D Embeddings | OpenCV Zoo (Self-hosted on Oracle Cloud) |
| **Semantic AI** | Multimodal Image Description & Moment Tagging | Google Gemini API (gemini-2.5-flash Free Tier) |
| **Task Queue** | Persistent Database-Backed Durable Queue | Built-in PostgreSQL / SQLite queue engine |

---

## What Works

- **Editorial Web UI:** High-contrast responsive design, camera capture via `getUserMedia`, multi-device upload queue.
- **Role-Based Collaboration:** Event owners, 7-day photographer invites with optional email restrictions, photographer revocation.
- **DSLR Auto-Uploader:** Zero-dependency Python desktop utility that monitors tethered camera folders, detects file stabilization, and uploads to ClickBook automatically.
- **Live Guest Gallery:** Instant QR code and secret link access with Server-Sent Events (SSE) live updates and polling fallback.
- **Dual Photo Upload Architecture:** Direct browser-to-R2 presigned upload flow to conserve server bandwidth, plus direct multipart uploads for the DSLR desktop utility.
- **OpenCV Face Matching:** Local YuNet face detection and SFace 128D embeddings. Consent-gated ephemeral selfie matching and tap-to-find face selection in event photos.
- **Google Gemini Semantic Intelligence:** Automatically identifies broad event context, categorizes moments (ceremonies, group photos, candids, celebrations), extracts searchable tags, and generates natural captions.
- **Persistent Job Queue:** Upload jobs survive restarts, feature automatic retries with exponential backoff, and separate heavy AI vision tasks from API request handling.
- **Dual Database & Storage Engines:** Neon PostgreSQL + Cloudflare R2 in production; zero-configuration SQLite + local disk in development.

---

## Local Development (Quick Start)

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
# Windows:
py -3.12 -m venv .venv
.\.venv\Scripts\activate
# Linux/macOS:
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Download OpenCV Zoo face detection & embedding weights
python models/download_models.py

# Run FastAPI backend with Uvicorn
uvicorn app.main:app --reload --port 8000
```

- API Docs: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
- Health Check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

- Web App: [http://localhost:5173](http://localhost:5173)

### 3. Run Backend Test Suite

```bash
cd backend
python -m pytest -v
```

---

## Production Deployment Guides

- **[MIGRATION_REPORT.md](MIGRATION_REPORT.md):** Complete architectural audit and migration report.
- **[DEPLOYMENT.md](DEPLOYMENT.md):** Master step-by-step production deployment guide.
- **[DATABASE_MIGRATION.md](DATABASE_MIGRATION.md):** Neon PostgreSQL setup and Alembic migrations.
- **[CLOUDFLARE_R2_SETUP.md](CLOUDFLARE_R2_SETUP.md):** Cloudflare R2 private bucket and presigned URL configuration.
- **[ORACLE_CLOUD_SETUP.md](ORACLE_CLOUD_SETUP.md):** Oracle Cloud Ampere A1 ARM64 VM, Docker, firewall, and Caddy HTTPS setup.
- **[GEMINI_SETUP.md](GEMINI_SETUP.md):** Google Gemini API setup and privacy safeguards.
- **[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md):** Complete environment variable reference catalog.
- **[SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md):** Production security and biometric privacy audit checklist.

---

## DSLR Tethered Camera Auto-Uploader

To automatically stream photos from a Nikon, Canon, or Sony camera tethering folder:

```bash
python uploader/clickbook_uploader.py \
  --api https://api.yourdomain.com \
  --event YOUR_EVENT_ID \
  --folder "C:\EventPhotos" \
  --email photographer@example.com
```

The tool will securely prompt for your password, monitor the directory for stable JPEGs, and stream them to ClickBook. Credentials are never written to disk.
