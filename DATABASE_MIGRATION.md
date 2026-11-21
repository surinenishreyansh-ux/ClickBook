# Neon PostgreSQL Database Setup & Migration Guide

ClickBook uses **Neon Serverless PostgreSQL** for production deployments while maintaining full backward-compatibility with SQLite for local development.

---

## 1. Create a Free Neon PostgreSQL Database

1. Sign up or log in at [Neon.tech](https://neon.tech).
2. Click **Create Project**.
3. Name your project (e.g. `clickbook-prod`) and select your preferred cloud region (e.g., `AWS us-east-2` or `eu-central-1`).
4. Once created, navigate to **Dashboard** > **Connection Details**.
5. Select **SQLAlchemy** or **Python** from the connection language dropdown.
6. Copy the connection string. It will look like:
   ```text
   postgresql://clickbook_user:your_password@ep-cool-sample-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

---

## 2. Configure DATABASE_URL in ClickBook

ClickBook uses the modern `psycopg` (v3) binary driver for asynchronous and pooled PostgreSQL connections.

In your production `.env` file, specify:
```env
DATABASE_URL=postgresql+psycopg://clickbook_user:your_password@ep-cool-sample-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
```

*(Note: If your URL starts with `postgresql://` or `postgres://`, ClickBook automatically translates it to `postgresql+psycopg://` at runtime.)*

---

## 3. Connection Pooling & Neon Auto-Suspend Resilience

Neon serverless computes automatically scale down or suspend after 5 minutes of inactivity to save compute hours within the Free Tier. When an incoming request arrives, Neon wakes up within 500ms to 2s.

ClickBook is engineered with built-in connection pool resilience:
```env
DB_POOL_SIZE=10        # Number of persistent connections kept in pool
DB_MAX_OVERFLOW=20     # Peak burst connections allowed
DB_POOL_TIMEOUT=30     # Seconds to wait for a connection before raising an error
DB_POOL_RECYCLE=300    # Reconnect every 5 minutes to prevent stale dropped sockets
```
The SQLAlchemy engine sets `pool_pre_ping=True`, testing connection vitality with a lightweight ping prior to executing queries, transparently reconnecting if Neon suspended the compute.

---

## 4. Running Migrations with Alembic

ClickBook includes Alembic database migrations in `backend/migrations/`.

### Run Migrations to Latest Version
From the `backend/` directory:
```bash
# On Linux / macOS / Oracle Cloud:
alembic upgrade head

# On Windows PowerShell:
.\.venv\Scripts\alembic.exe upgrade head
```

### Automatic Table Initialization
If you start the FastAPI container or application directly without manually running Alembic, `app.db.init_db()` automatically runs `Base.metadata.create_all(engine)` on startup, ensuring that all tables exist before serving traffic.

### Create New Migrations (Developers)
When modifying models in `backend/app/db.py`:
```bash
alembic revision --autogenerate -m "describe_changes_here"
alembic upgrade head
```

---

## 5. Local Development Fallback

For local offline development or automated tests without a Neon account:
```env
DATABASE_URL=sqlite:///data/clickbook.sqlite3
```
ClickBook activates SQLite-specific WAL journaling, foreign key pragmas, and thread safety configurations automatically.
