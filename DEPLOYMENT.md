# ClickBook — Production Deployment Master Guide

This guide takes you step-by-step through deploying the complete ClickBook production architecture for a **low-cost pilot within free-tier limits** (availability and usage not guaranteed):

- **Frontend:** React + Vite on **Cloudflare Pages** (Free)
- **Photo Storage:** **Cloudinary authenticated assets** (Free plan, usage-based credits; no payment card needed)
- **Database:** **Neon Serverless PostgreSQL** (Free Tier)
- **Backend Compute:** **Oracle Cloud Infrastructure (OCI) Always Free** Ampere A1 ARM64 (Free)
- **Semantic Vision:** **Google Gemini API** (Free Tier)
- **Face Biometrics:** **OpenCV YuNet + SFace** (Self-hosted on Oracle Cloud)

---

## Architecture Overview

```text
       [ Guest Browser / Photographer Phone / DSLR Uploader ]
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
[ Cloudflare Pages ]                            [ Oracle Cloud VM ]
  React + Vite SPA                                Caddy Reverse Proxy (HTTPS)
  Custom Domain: photos.domain.com                       │
        │                                         FastAPI Backend (Docker)
        │                                         ├── OpenCV YuNet/SFace (Local)
        │                                         ├── Persistent Job Queue
        │                                         └── Gemini API Client
        │                                                │
        ├──────────────────────┬─────────────────────────┤
        ▼                      ▼                         ▼
 [ Cloudinary ]       [ Neon PostgreSQL ]      [ Google Gemini API ]
  Authenticated Photos    Serverless DB           Semantic Metadata
  Backend-Gated Images    Alembic Migrations      Tags & Moment Types
```

---

## Step 1: Set Up Neon Serverless PostgreSQL

1. Sign up for free at [Neon.tech](https://neon.tech).
2. Click **Create Project**, name it `clickbook-prod`, and choose your region.
3. In **Connection Details**, select **SQLAlchemy** and copy your connection string:
   ```text
   postgresql://USER:PASSWORD@ep-sample-123.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Save this as your `DATABASE_URL`.

---

## Step 2: Set Up Cloudinary Photo Storage

1. Create a Cloudinary Free account at https://cloudinary.com/users/register_free
   (no card required). Follow **[CLOUDINARY_SETUP.md](CLOUDINARY_SETUP.md)**.
2. In the Cloudinary Console, copy your cloud name, API key, and API secret
   into a private server-side `.env` file.
3. Set `STORAGE_DRIVER=cloudinary`, and add
   `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and
   `CLOUDINARY_API_SECRET`.
4. Do **not** publish the API secret to frontend JavaScript or Git.
5. Photos are uploaded as Cloudinary `authenticated` assets and returned
   through ClickBook's protected image endpoints. The backend serves media
   bytes and may require more bandwidth than direct R2 delivery.

R2 remains available as an optional alternative if you activate it later.

---

## Step 3: Get Google Gemini API Key (Optional)

1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Create an API key.
3. Save it as `GEMINI_API_KEY`. (If you skip this step, ClickBook runs with Gemini disabled, and face recognition continues working normally).

---

## Step 4: Deploy Backend on Oracle Cloud (OCI)

1. Create an Ubuntu 24.04 ARM64 instance (Ampere A1) in the Oracle Cloud Console (see `ORACLE_CLOUD_SETUP.md`).
2. In the OCI VCN Security List, open TCP ports **80** and **443**.
3. In Cloudflare DNS, create an **A record**:
   - **Name:** `api` (e.g. `api.yourdomain.com`)
   - **IPv4 Address:** Your Oracle Cloud instance Public IP
   - **Proxy Status:** DNS only (Grey Cloud) initially so Caddy can provision the SSL certificate.
4. SSH into the instance:
   ```bash
   ssh -i your_key.key ubuntu@YOUR_INSTANCE_IP
   ```
5. Configure host firewall and install Docker:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 iptables-persistent
   sudo netfilter-persistent save
   sudo usermod -aG docker $USER
   newgrp docker
   ```
6. Clone the repository and configure `.env`:
   ```bash
   git clone https://github.com/your-username/clickbook.git
   cd clickbook
   cp .env.example .env
   nano .env
   ```
   Set your Neon `DATABASE_URL`, Cloudinary credentials, `STORAGE_DRIVER=cloudinary`, `SECRET_KEY`, and `DOMAIN=api.yourdomain.com`.
7. Start the application:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
8. Verify health:
   ```bash
   curl https://api.yourdomain.com/api/health
   ```
   Output should show `{"status":"ok", "database_connected":true, "ai_models_ready":true}`.

---

## Step 5: Deploy Frontend to Cloudflare Pages

1. In the Cloudflare Dashboard, go to **Workers & Pages** > **Create application** > **Pages** > **Connect to Git**.
2. Select your ClickBook repository.
3. Configure build settings:
   - **Framework preset:** `Vite`
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
4. Under **Environment variables**, add:
   - `VITE_API_BASE_URL` = `https://api.yourdomain.com`
5. Click **Save and Deploy**.
6. Under **Custom domains**, add your custom domain (e.g., `photos.yourdomain.com`).

*(Note: The file `frontend/public/_redirects` ensures that SPA routes like `/g/CODE`, `/app`, and `/invite/TOKEN` load seamlessly without 404 errors).*

---

## Step 6: Connect and Test Your Live Event

1. Open `https://photos.yourdomain.com`.
2. Register a new organizer account.
3. Create your first event.
4. Scan the guest QR code with your phone or open the guest link.
5. Upload a photo from your phone or camera tether folder using the DSLR uploader.
6. Watch the photo appear live in the guest gallery via Server-Sent Events!
