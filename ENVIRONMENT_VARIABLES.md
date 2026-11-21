# ClickBook Environment Variables Reference

All runtime configuration for ClickBook is governed through environment variables.

---

## Complete Variable Catalog

| Variable Name | Required | Default Value | Description |
|---|---|---|---|
| `ENVIRONMENT` | Yes | `development` | Set to `production` in live environments to enforce security and secret checks. |
| `SECRET_KEY` | Yes (in prod) | *insecure-dev-key* | 64-character random hex string used for session hashes and tokens. |
| `DATABASE_URL` | Yes | `sqlite:///data/clickbook.sqlite3` | PostgreSQL connection string (`postgresql+psycopg://...sslmode=require`) or SQLite URI. |
| `DB_POOL_SIZE` | No | `10` | SQLAlchemy persistent connection pool size for Neon PostgreSQL. |
| `DB_MAX_OVERFLOW` | No | `20` | Max overflow burst connections for Neon PostgreSQL. |
| `DB_POOL_TIMEOUT` | No | `30` | Seconds to wait for a database connection before timing out. |
| `DB_POOL_RECYCLE` | No | `300` | Connection recycling frequency in seconds (prevents stale sockets during Neon auto-suspend). |
| `STORAGE_DRIVER` | Yes | `local` | `cloudinary` for private Cloudinary assets, `r2` for R2, or `local` for development. |
| `CLOUDINARY_CLOUD_NAME` | When `cloudinary` | None | Cloudinary cloud name; backend only. |
| `CLOUDINARY_API_KEY` | When `cloudinary` | None | Cloudinary API key; backend only. |
| `CLOUDINARY_API_SECRET` | When `cloudinary` | None | Sensitive Cloudinary API secret. Never commit or expose to frontend. |
| `CLOUDINARY_MAX_ASSET_MB` | No | `10` | Maximum uploaded derivative size in MiB for the Cloudinary Free plan. |
| `R2_ACCOUNT_ID` | When `r2` | None | Your 32-character Cloudflare Account ID from the Cloudflare dashboard. |
| `R2_ACCESS_KEY_ID` | When `r2` | None | Cloudflare R2 S3 API Access Key ID. |
| `R2_SECRET_ACCESS_KEY` | When `r2` | None | Cloudflare R2 S3 API Secret Access Key. |
| `R2_BUCKET_NAME` | When `r2` | None | Private Cloudflare R2 bucket name (e.g. `clickbook-photos-prod`). |
| `R2_ENDPOINT_URL` | No | *auto-derived* | Custom S3 endpoint URL. If omitted, derived from `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`. |
| `R2_PUBLIC_BASE_URL` | No | None | Optional public CDN URL if bucket has custom domain assigned. |
| `GEMINI_API_KEY` | Optional | None | Google AI Studio API key for multimodal image categorization and tagging. |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Supported Google Gemini model identifier. |
| `FRONTEND_URL` | Yes | `http://localhost:5173` | Public URL of the Cloudflare Pages React application. |
| `CLICKBOOK_ORIGINS` | No | *localhost, 5173, 8000* | Comma-separated list of allowed CORS browser origins. |
| `DOMAIN` | When using Caddy | `localhost` | Primary domain for automatic HTTPS Let's Encrypt certificates (e.g. `api.yourdomain.com`). |
| `MAX_IMAGE_MB` | No | `25` | Maximum permissible single photo upload size in megabytes. |
| `FACE_THRESHOLD` | No | `0.43` | Cosine similarity threshold for face match detection (0.0 to 1.0). |
| `CLUSTER_THRESHOLD` | No | `0.48` | Cosine similarity threshold for event face group clustering. |
| `FACE_MODEL_DIR` | No | `/app/models` | Filesystem path where YuNet and SFace ONNX weight files reside. |

---

## Frontend Environment Variables (Cloudflare Pages)

| Variable Name | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | *(empty)* | Full public HTTPS URL of your Oracle Cloud backend (e.g. `https://api.yourdomain.com`). In local dev, Vite proxies `/api` to `http://127.0.0.1:8000`. |
