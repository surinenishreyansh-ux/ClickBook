# Cloudflare R2 Photo Storage Setup Guide

ClickBook uses **Cloudflare R2** for private, S3-compatible, zero-egress-fee photo storage. Original photos, high-resolution views, and thumbnails are stored securely with time-limited presigned URLs.

---

## 1. Create a Cloudflare R2 Bucket

1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. In the left navigation sidebar, select **R2 Storage**.
3. If this is your first time using R2, activate R2 (includes **10 GB/month free storage**, 1 million Class A operations, 10 million Class B operations, and **$0 egress fees**).
4. Click **Create bucket**.
5. Name your bucket (e.g., `clickbook-photos-prod`).
6. Leave the bucket **Private** (default). Do not enable public access.
7. Click **Create Bucket**.

---

## 2. Generate Cloudflare R2 API Tokens

1. In the R2 Dashboard, click **Manage R2 API Tokens** in the right-hand panel.
2. Click **Create API token**.
3. Choose token permissions:
   - **Permissions:** `Object Read & Write`
   - **Specify bucket(s):** Apply to your specific bucket (`clickbook-photos-prod`) or all buckets.
   - **TTL:** Leave blank or set according to your organization's security policy.
4. Click **Create API Token**.
5. Copy the following values immediately:
   - **Access Key ID**
   - **Secret Access Key**
   - **Endpoint** (format: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`)

---

## 3. Configure CORS on Your R2 Bucket

To allow browsers to upload photos directly to your R2 bucket via presigned PUT URLs, configure CORS on the bucket:

1. Open your bucket in the Cloudflare R2 dashboard.
2. Go to **Settings** > **CORS Policy**.
3. Click **Add CORS rule** and paste the following JSON:
```json
[
  {
    "AllowedOrigins": [
      "https://photos.yourdomain.com",
      "http://localhost:5173",
      "http://localhost:8000"
    ],
    "AllowedMethods": [
      "GET",
      "PUT",
      "HEAD"
    ],
    "AllowedHeaders": [
      "*"
    ],
    "ExposeHeaders": [
      "ETag"
    ],
    "MaxAgeSeconds": 3600
  }
]
```
4. Save the CORS policy.

---

## 4. Configure Environment Variables in ClickBook

Add the following to your `.env` file on Oracle Cloud:

```env
STORAGE_DRIVER=r2
R2_ACCOUNT_ID=your_32_character_cloudflare_account_id
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_BUCKET_NAME=clickbook-photos-prod
```

---

## 5. Storage Architecture & Object Hierarchy

ClickBook organizes images under a clean, deterministic hierarchy:

```text
{event_id}/
  {photo_id}/
    full.jpg     # Stripped full-resolution original (up to 4000px, quality 89)
    view.jpg     # Fast display view for web gallery & AI inference (1600px, quality 85)
    thumb.jpg    # Lightweight responsive gallery thumbnail (650px, quality 80)
```

### Security & Presigned URLs:
- **Private by Default:** The bucket has no public URL.
- **Upload Flow:** The browser requests upload authorization via `POST /api/events/{eid}/photos/request-upload`. FastAPI generates a 15-minute presigned PUT URL. The client uploads directly to R2. FastAPI verifies the upload via `head_object` before committing the DB record.
- **Download Flow:** When guests or event teams access full images or thumbnails, FastAPI issues a `302 Redirect` to a 15-minute time-limited presigned GET URL generated via AWS SigV4. Cloudflare serves the media directly, preserving Oracle Cloud bandwidth.
- **DSLR Auto-Uploader:** Compatible with direct multipart upload to `POST /api/events/{eid}/photos`, where the backend server handles tier encoding and R2 streaming transparently.
