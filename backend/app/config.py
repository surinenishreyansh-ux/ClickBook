import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger('clickbook.config')

BASE = Path(__file__).resolve().parents[1]
# Uvicorn and Alembic do not load .env by default. Explicit process env wins.
load_dotenv(BASE.parent / '.env', override=False)
load_dotenv(BASE / '.env', override=False)
DATA = Path(os.environ.get('CLICKBOOK_DATA', str(BASE / 'data')))
DATA.mkdir(parents=True, exist_ok=True)

# Database Configuration (Neon PostgreSQL or SQLite)
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{DATA / "clickbook.sqlite3"}')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgres://'):]
elif DATABASE_URL.startswith('postgresql://') and not DATABASE_URL.startswith('postgresql+'):
    DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgresql://'):]

# Connection pooling settings (critical for Neon serverless PostgreSQL)
DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '10'))
DB_MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW', '20'))
DB_POOL_TIMEOUT = int(os.environ.get('DB_POOL_TIMEOUT', '30'))
DB_POOL_RECYCLE = int(os.environ.get('DB_POOL_RECYCLE', '300'))

# Security and CORS
SECRET_KEY = os.environ.get('SECRET_KEY', 'clickbook-insecure-dev-key-change-in-production')
ALLOWED_ORIGINS = [
    s.strip() for s in os.environ.get(
        'CLICKBOOK_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000'
    ).split(',') if s.strip()
]
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173').rstrip('/')
if FRONTEND_URL and FRONTEND_URL not in ALLOWED_ORIGINS:
    ALLOWED_ORIGINS.append(FRONTEND_URL)

MAX_IMAGE_MB = int(os.environ.get('MAX_IMAGE_MB', '25'))
FACE_THRESHOLD = float(os.environ.get('FACE_THRESHOLD', '0.43'))
CLUSTER_THRESHOLD = float(os.environ.get('CLUSTER_THRESHOLD', '0.48'))
MODEL_DIR = Path(os.environ.get('FACE_MODEL_DIR', str(BASE / 'models')))
APP_VERSION = '1.1.0'

# Storage Configuration (Cloudinary, Cloudflare R2, or Local)
STORAGE_DRIVER = os.environ.get('STORAGE_DRIVER', '').lower()
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '').strip()
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '').strip()
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '').strip()
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', '').strip()
R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL', '').strip()
R2_PUBLIC_BASE_URL = os.environ.get('R2_PUBLIC_BASE_URL', '').strip().rstrip('/')

# Backward compatibility with legacy S3_* env vars
if not STORAGE_DRIVER:
    if R2_BUCKET_NAME or os.environ.get('S3_BUCKET'):
        STORAGE_DRIVER = 'r2'
    else:
        STORAGE_DRIVER = 'local'

if STORAGE_DRIVER in ('s3', 'r2'):
    STORAGE_DRIVER = 'r2'
    STORAGE_BUCKET = R2_BUCKET_NAME or os.environ.get('S3_BUCKET', '')
    STORAGE_ACCESS_KEY = R2_ACCESS_KEY_ID or os.environ.get('AWS_ACCESS_KEY_ID', '')
    STORAGE_SECRET_KEY = R2_SECRET_ACCESS_KEY or os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    if not R2_ENDPOINT_URL and R2_ACCOUNT_ID:
        STORAGE_ENDPOINT = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
    else:
        STORAGE_ENDPOINT = R2_ENDPOINT_URL or os.environ.get('S3_ENDPOINT_URL', '')
    STORAGE_REGION = os.environ.get('S3_REGION', 'auto')
else:
    if STORAGE_DRIVER not in ('local', 'cloudinary'):
        raise RuntimeError('Unsupported STORAGE_DRIVER; choose local, r2, or cloudinary')
    STORAGE_BUCKET = ''
    STORAGE_ACCESS_KEY = ''
    STORAGE_SECRET_KEY = ''
    STORAGE_ENDPOINT = ''
    STORAGE_REGION = 'auto'

# Cloudinary authenticated private image storage (card-free starter option)
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '').strip()
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '').strip()
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '').strip()
CLOUDINARY_FOLDER = 'clickbook'  # Fixed prefix; all remote assets are event-scoped
CLOUDINARY_MAX_ASSET_MB = int(os.environ.get('CLOUDINARY_MAX_ASSET_MB', '10'))

# Google Gemini API
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip()

# Production configuration validation
IS_PRODUCTION = os.environ.get('ENVIRONMENT', 'development').lower() in ('production', 'prod')

def validate_production_config():
    """Validate critical environment variables in production without leaking secrets."""
    missing = []
    if IS_PRODUCTION:
        if DATABASE_URL.startswith('sqlite'):
            log.warning('PRODUCTION WARNING: DATABASE_URL is pointing to SQLite. Neon PostgreSQL is recommended.')
        if SECRET_KEY == 'clickbook-insecure-dev-key-change-in-production':
            missing.append('SECRET_KEY (cannot use default development key in production)')
        if STORAGE_DRIVER == 'cloudinary':
            if not CLOUDINARY_CLOUD_NAME: missing.append('CLOUDINARY_CLOUD_NAME')
            if not CLOUDINARY_API_KEY: missing.append('CLOUDINARY_API_KEY')
            if not CLOUDINARY_API_SECRET: missing.append('CLOUDINARY_API_SECRET')
        if STORAGE_DRIVER == 'r2':
            if not STORAGE_BUCKET: missing.append('R2_BUCKET_NAME')
            if not STORAGE_ACCESS_KEY: missing.append('R2_ACCESS_KEY_ID')
            if not STORAGE_SECRET_KEY: missing.append('R2_SECRET_ACCESS_KEY')
            if not STORAGE_ENDPOINT: missing.append('R2_ACCOUNT_ID or R2_ENDPOINT_URL')
    if missing:
        msg = f"CRITICAL: Missing required configuration variables for production: {', '.join(missing)}"
        log.error(msg)
        raise RuntimeError(msg)

# The only allowed incomplete-production state is the maintenance-only bootstrap:
# HTTP middleware blocks all public routes except health until secrets are set.
SETUP_MODE = os.environ.get('CLICKBOOK_SETUP_MODE', '0').lower() in ('1', 'true', 'yes')
if IS_PRODUCTION and not SETUP_MODE:
    validate_production_config()
elif IS_PRODUCTION and SETUP_MODE:
    log.warning('ClickBook in setup mode: application traffic disabled until secrets are configured')
