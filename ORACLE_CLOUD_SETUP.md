# Oracle Cloud Infrastructure (OCI) Deployment Guide

This guide walks through deploying the ClickBook backend to an **Oracle Cloud Infrastructure (OCI) Always Free** compute instance using Docker and Caddy with automatic HTTPS.

---

## 1. Create an OCI Always Free Compute Instance

Oracle Cloud provides up to 4 OCPU and 24 GB RAM for free on Ampere A1 ARM64 architecture:

1. Log in to your [Oracle Cloud Console](https://cloud.oracle.com/).
2. Navigate to **Compute** > **Instances** > **Create Instance**.
3. Name your instance (e.g., `clickbook-backend`).
4. **Placement:** Select your default Availability Domain.
5. **Image and Shape:**
   - **Image:** Ubuntu 24.04 or 22.04 LTS (Minimal or Standard).
   - **Shape:** Click **Change Shape** > **Ampere** > **VM.Standard.A1.Flex** (select 2–4 OCPUs and 12–24 GB Memory).
   *(If ARM is not available in your region, choose AMD `VM.Standard.E2.1.Micro`).*
6. **Networking:**
   - Select your default Virtual Cloud Network (VCN) and public subnet.
   - Assign a public IPv4 address.
7. **Add SSH keys:** Generate and download your SSH private key.
8. Click **Create**.

---

## 2. Configure OCI VCN Security List (Ingress Firewall)

You must open ports 80 and 443 in your Oracle Cloud Virtual Cloud Network:

1. In the OCI Console, go to **Networking** > **Virtual Cloud Networks**.
2. Click your VCN > **Security Lists** > **Default Security List for...**.
3. Click **Add Ingress Rules**:
   - **Source CIDR:** `0.0.0.0/0`
   - **IP Protocol:** `TCP`
   - **Destination Port Range:** `80,443`
   - **Description:** `Allow HTTP and HTTPS traffic`
4. Click **Add Ingress Rules**.
5. Add another rule for UDP port 443 if you wish to enable HTTP/3:
   - **Source CIDR:** `0.0.0.0/0`, **IP Protocol:** `UDP`, **Destination Port Range:** `443`.

---

## 3. Configure Ubuntu OS Firewall

SSH into your Oracle Cloud instance:
```bash
ssh -i /path/to/your_private_key.key ubuntu@YOUR_INSTANCE_PUBLIC_IP
```

Oracle Cloud Ubuntu images include strict `iptables` rules by default. Run the following commands to permit web traffic through the host OS firewall:

```bash
# Allow HTTP, HTTPS and internal Docker traffic
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT

# Save iptables rules across reboots
sudo apt-get update && sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

---

## 4. Install Docker & Docker Compose on Ubuntu ARM64

```bash
# Install Docker prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Set up Docker repository (automatically detects ARM64 or x86_64)
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker engine and compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow ubuntu user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

---

## 5. Clone and Deploy ClickBook

1. Clone your ClickBook repository onto the instance:
```bash
git clone https://github.com/your-username/clickbook.git /home/ubuntu/clickbook
cd /home/ubuntu/clickbook
```

2. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
nano .env
```

3. Fill in your production credentials:
   - `DATABASE_URL` (Neon PostgreSQL)
   - `SECRET_KEY` (Generate via `python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`
   - `GEMINI_API_KEY`
   - `DOMAIN=api.yourdomain.com` (Ensure your DNS A record points `api.yourdomain.com` to this instance's public IP)
   - `FRONTEND_URL=https://photos.yourdomain.com`

4. Launch with Docker Compose:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

5. Verify health:
```bash
# Check running containers
docker compose -f docker-compose.prod.yml ps

# View backend logs
docker compose -f docker-compose.prod.yml logs -f clickbook

# Test local healthcheck
curl -i http://localhost:8000/api/health
```

The Caddy reverse proxy will automatically obtain a valid Let's Encrypt SSL/TLS certificate for your domain as soon as DNS propagates!
