# ClickBook Production Security Checklist

Review this checklist before publishing your ClickBook installation to production with client or event photographs.

---

### 1. Storage & Cloudflare R2
- [x] **Private Buckets:** Verify that your Cloudflare R2 bucket does NOT have public bucket access enabled.
- [x] **Time-Limited URLs:** Confirm that presigned download and upload URLs expire after 15 minutes (900 seconds).
- [x] **Credential Isolation:** R2 API tokens are passed via server-side environment variables and never exposed to the frontend browser bundle.
- [x] **Upload Validation:** Uploaded files are verified for size (max 25 MB), EXIF-stripped, and re-encoded into JPEGs before permanent storage.

---

### 2. Database & Neon PostgreSQL
- [x] **Enforce SSL:** Ensure `sslmode=require` is present in your Neon `DATABASE_URL`.
- [x] **Connection Pooling:** Ensure `pool_pre_ping=True` and `pool_recycle=300` are configured in SQLAlchemy to handle Neon compute sleep/wake cycles.
- [x] **Zero Plaintext Passwords:** User passwords must be hashed using salted `scrypt` (`n=2**14, r=8, p=1`).
- [x] **Session Invalidation:** Sessions expire after 14 days and are stored as SHA-256 hashes in PostgreSQL; logging out explicitly revokes the session.
- [x] **SQL Injection Defense:** All queries use SQLAlchemy ORM or parameterized expressions; no raw string concatenation is used.

---

### 3. Biometric & AI Privacy
- [x] **Biometric Consent Enforcement:** Face search requires explicit user consent checkboxes before initiating search queries.
- [x] **Ephemeral Guest Selfies:** Selfies taken by guests to search for photos are processed strictly in RAM and are NEVER saved to disk, PostgreSQL, or Cloudflare R2.
- [x] **No External Biometric Leakage:** Selfies and 128D face vectors are NEVER transmitted to Google Gemini, Google Cloud, or third-party APIs.
- [x] **Event-Scoped Face Search:** Guests can only search for faces within the specific event tied to their guest QR code.
- [x] **Right to Deletion:** Disabling face search or deleting an event immediately deletes all face bounding boxes and embeddings from PostgreSQL.

---

### 4. Network & Server Security (Oracle Cloud)
- [x] **Unprivileged Container:** The production Docker container executes under a non-root `clickbook` user (UID 10001).
- [x] **HTTPS Only:** Caddy or Nginx enforces TLS 1.2+ with automatic Let's Encrypt certificates and HSTS headers.
- [x] **Firewall Ingress:** Only ports 80 and 443 are open to the internet in the OCI Security List. Port 22 (SSH) should be restricted to your administrative IP where feasible.
- [x] **CORS Whitelisting:** Only designated frontend domains (`FRONTEND_URL` and `CLICKBOOK_ORIGINS`) are permitted to send authenticated cross-origin requests.
- [x] **Rate Limiting:** In-memory sliding-window rate limiters throttle facial recognition and search endpoints to prevent abuse.
