# Cloudinary setup — ClickBook private photo storage

ClickBook supports Cloudinary as a **card-free starting storage provider**. The
Cloudinary Free plan has usage limits and **must be monitored during events**.

## Step 1 — Create and secure an account

1. Open https://cloudinary.com/users/register_free and create an account.
2. Open **Cloudinary Console** and select your product environment.
3. In **API Keys** (or the credentials panel), find:
   - Cloud name
   - API key
   - API secret
4. Store these securely. The API secret belongs **only on the FastAPI backend**,
   never in Git, frontend variables, or the React application.
5. Turn on 2FA. Review available credits/usage before a client event.

## Step 2 — Configure ClickBook

In your server's private `.env` (NOT `.env.example`):

```env
STORAGE_DRIVER=cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
CLOUDINARY_MAX_ASSET_MB=10
```

You do **not** need Cloudflare R2 credentials when this driver is selected.
Keep your Neon `DATABASE_URL`, `SECRET_KEY`, `CLICKBOOK_ORIGINS`, and
`FRONTEND_URL` unchanged. Use HTTPS on the deployed site.

Install dependencies and start the existing FastAPI app:

```sh
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

For Docker deployments, put the variables in the root `.env`, then rebuild
using `docker compose -f docker-compose.prod.yml up -d --build`.

## What happens to photographs

- **Only logged-in authorized photographers** can upload via
  `POST /api/events/{eid}/photos`, including phone camera and DSLR uploader.
- The backend validates the image, removes EXIF, adapts large originals to the Free plan's 10 MiB per-image limit, and generates full/view/thumb
  JPEG versions, and uploads each with Cloudinary delivery
  `type=authenticated` to an event-specific folder.
- The guest website continues to use ClickBook's QR gallery and
  `/api/g/{code}/photos/{pid}/image` routes. It receives the bytes through the
  backend; **Cloudinary signed download URLs aren't revealed in the browser**.
- Face detection and embeddings remain on the FastAPI server. Cloudinary only
  stores the event photos, not face vectors or guest selfie queries.
- This intentionally uses backend proxying rather than public CDN image URLs.
  Watch backend bandwidth/latency and Cloudinary usage as guest traffic grows.

**Do not change uploads to `type=upload` or `type=private`.** Public uploads
are accessible to anyone with the URL, and Cloudinary `private` assets can
still expose transformations. `authenticated` protects originals and variants.

## Step 3 — Pilot test before a paying client

1. Register an organizer, create an event and scan its guest QR.
2. Invite a photographer and accept the invitation from their account.
3. Upload a JPEG from the photographer account; guest gallery should update.
4. Verify the image is **authenticated** in Cloudinary Media Library.
5. Open the image through the ClickBook guest QR URL.
6. Verify an unapproved account cannot upload.
7. Delete an image and confirm it disappears from Cloudinary.
8. Switch on face search only with participant consent and installed models;
   test with consented photos of multiple people.
9. Watch API response time, Cloudinary usage, Neon connections, and background
   worker health during a realistic multi-phone upload test.

## Troubleshooting

- **Cloudinary credentials missing:** set all 3 required backend variables and restart.
- **503 on uploads:** confirm account, API credentials, active plan, and quota.
- **503 on images:** verify the asset has type `authenticated`, API credentials
  are correct, and the server can contact `https://api.cloudinary.com`.
- **Nothing appears in the gallery:** check the backend upload logs and the
  background queue, then load `/api/health`.
- **Neon still works:** storage and PostgreSQL configurations are independent.
- **Already using R2:** this is not an automatic migration. Leave
  `STORAGE_DRIVER=r2` until any old media is migrated.

## Important limitations

Cloudinary's Free plan has a monthly credit allowance; it is not unlimited.
The paid scale-out storage/design decisions and real-event privacy, security,
biometric-consent and load tests are still required before accepting customers.
