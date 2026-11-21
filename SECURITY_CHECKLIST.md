# ClickBook Production Security Checklist

Review this checklist before publishing your ClickBook installation to production with client or event photographs.

---

### 1. Storage & Cloudinary (pilot default)
- [x] **Authenticated originals and variants:** The Cloudinary adapter uploads all
  three JPEG versions with delivery `type=authenticated`, never public URLs.
- [x] **Backend-mediated delivery:** Event QR access is checked by ClickBook
  before fetching signed photos on the server. Client browsers do not receive
  Cloudinary download URLs.
- [x] **Authenticated uploads:** Phone/DSLR uploads require an approved
  photographer account. Unauthenticated local PUT paths are removed.
- [x] **Image normalization:** Source images are EXIF-stripped and encoded
  into three JPEG sizes before upload.
- [ ] **Live Cloudinary check:** Confirm real assets are marked
  `authenticated`, do not load without authorization, and deletion succeeds.
- [ ] **Quota / load test:** Measure Cloudinary credits, VM egress/bandwidth,
  and guest image latency under realistic multi-guest load.
- [ ] **Credential hygiene:** Review Git history for inadvertently committed
  credentials; rotate any exposed database password. Do not commit `.env`.
- [ ] **Account resilience:** Test provider outages and confirm storage
  deletion errors are reported and retried.

Cloudflare R2 remains an optional alternative and is not enabled by default.
Cloudinary's Free plan has limited credits and does not guarantee production
scale. See [CLOUDINARY_SETUP.md](CLOUDINARY_SETUP.md).

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
