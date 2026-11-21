import hashlib
import io
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, delete, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from PIL import Image, ImageOps, UnidentifiedImageError
from .config import (
    ALLOWED_ORIGINS, MAX_IMAGE_MB, APP_VERSION, STORAGE_DRIVER,
    GEMINI_API_KEY, IS_PRODUCTION, CLOUDINARY_MAX_ASSET_MB
)
from .db import (
    init_db, get_db, SessionLocal, User, Session as LoginSession,
    Event, Member, Invite, Photo, Face, Job, uid, now
)
from .security import (
    make_password, check_password, new_session, current_user,
    must_owner, must_member, revoke_session
)
from .storage import store
from . import face_ai
from . import gemini_ai
from . import queue

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('clickbook')
Image.MAX_IMAGE_PIXELS = 80_000_000

@asynccontextmanager
async def lifespan(_app):
    """Start durable background job worker and resume interrupted tasks."""
    queue.start_worker()
    try:
        yield
    finally:
        queue.stop_worker()

app = FastAPI(
    title='Clickbook API',
    version=APP_VERSION,
    docs_url='/api/docs',
    openapi_url='/api/openapi.json',
    lifespan=lifespan
)

# Fail closed during infrastructure provisioning. Never accept real customer
# data on an ephemeral SQLite / local-storage fallback.
@app.middleware('http')
async def setup_gate(request: Request, call_next):
    if os.environ.get('CLICKBOOK_SETUP_MODE', '0').lower() in ('1', 'true', 'yes'):
        # Render's default startup health probe sends HEAD /.
        # Keep it healthy while all user-facing routes remain disabled.
        if request.method == 'HEAD' and request.url.path == '/':
            return Response(status_code=200, headers={'Cache-Control': 'no-store'})
        if request.url.path != '/api/health':
            return JSONResponse(
                status_code=503,
                content={'detail': 'ClickBook is being configured. Please try again later.'},
                headers={'Cache-Control': 'no-store'}
            )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'PUT', 'OPTIONS'],
    allow_headers=['*']
)

init_db()

# --- Request Models ---

class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class EventCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    location: str = Field(default='', max_length=150)
    event_date: str = Field(default='', max_length=32)

class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    location: str | None = Field(default=None, max_length=150)
    event_date: str | None = Field(default=None, max_length=32)
    status: Literal['live', 'closed'] | None = None
    face_enabled: bool | None = None
    downloads_enabled: bool | None = None

class InviteCreate(BaseModel):
    email: EmailStr | None = None

class Consent(BaseModel):
    accepted: bool

class FacePoint(BaseModel):
    photo_id: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    consent: bool

class PresignedUploadRequest(BaseModel):
    filename: str = Field(max_length=240)
    content_type: str = Field(default='image/jpeg')
    file_size: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)

class ConfirmUploadRequest(BaseModel):
    photo_id: str = Field(min_length=32, max_length=32)
    sha256: str = Field(min_length=64, max_length=64)
    original_name: str = Field(max_length=240)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

# --- Rate Limiting ---

_limit_lock = threading.Lock()
_face_requests = defaultdict(deque)

def rate_limit(request: Request, code: str):
    ip = request.client.host if request.client else 'unknown'
    key = (code, ip)
    with _limit_lock:
        q = _face_requests[key]
        t = time.monotonic()
        while q and q[0] < t - 60:
            q.popleft()
        if len(q) >= 20:
            raise HTTPException(429, 'Too many requests. Please wait a minute before retrying.')
        q.append(t)
        if len(_face_requests) > 5000:
            for k in list(_face_requests.keys())[:500]:
                if not _face_requests[k] or _face_requests[k][-1] < t - 60:
                    _face_requests.pop(k, None)

# --- Helpers ---

def get_event(db: DbSession, eid: str) -> Event:
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404, 'Event not found')
    return e

def get_guest_event(db: DbSession, code: str) -> Event:
    e = db.scalar(select(Event).where(Event.guest_code == code))
    if not e:
        raise HTTPException(404, 'This event link is invalid or has been reset')
    return e

def event_out(db: DbSession, e: Event, user: User | None = None) -> dict:
    count = db.scalar(select(func.count(Photo.id)).where(Photo.event_id == e.id)) or 0
    members = db.scalar(select(func.count(Member.id)).where(Member.event_id == e.id)) or 0
    role = 'owner' if user and e.owner_id == user.id else 'photographer'
    return {
        'id': e.id,
        'title': e.title,
        'location': e.location,
        'event_date': e.event_date,
        'status': e.status,
        'guest_code': e.guest_code,
        'face_enabled': e.face_enabled,
        'downloads_enabled': e.downloads_enabled,
        'created_at': e.created_at.isoformat(),
        'photo_count': count,
        'photographer_count': members,
        'role': role
    }

def photo_out(p: Photo) -> dict:
    return {
        'id': p.id,
        'created_at': p.created_at.isoformat(),
        'width': p.width,
        'height': p.height,
        'face_status': p.face_status,
        'face_count': p.face_count,
        'gemini_status': p.gemini_status,
        'gemini_description': p.gemini_description,
        'gemini_context': p.gemini_context,
        'gemini_moment_type': p.gemini_moment_type,
        'gemini_tags': p.gemini_tags,
        'gemini_caption': p.gemini_caption,
        'original_name': p.original_name
    }

# --- System & Health ---

@app.get('/api/health')
def health(db: DbSession = Depends(get_db)):
    db_ok = True
    try:
        db.scalar(select(func.count(User.id)))
    except Exception:
        db_ok = False
    return {
        'status': 'ok' if db_ok else 'database_error',
        'version': APP_VERSION,
        'database_connected': db_ok,
        'ai_models_ready': face_ai.models_available(),
        'storage_driver': store.driver,
        'gemini_ready': gemini_ai.is_gemini_available(),
        'setup_required': os.environ.get('CLICKBOOK_SETUP_MODE', '0').lower() in ('1', 'true', 'yes')
    }

# --- Auth Routes ---

@app.post('/api/auth/register', status_code=201)
def register(body: Credentials, db: DbSession = Depends(get_db)):
    email = str(body.email).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'An account with this email already exists')
    salt, pw_hash = make_password(body.password)
    user = User(id=uid(), email=email, password_salt=salt, password_hash=pw_hash)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Email already registered')
    return {'token': new_session(db, user), 'email': user.email, 'id': user.id}

@app.post('/api/auth/login')
def login(body: Credentials, db: DbSession = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not u or not check_password(body.password, u.password_salt, u.password_hash):
        raise HTTPException(401, 'Incorrect email or password')
    return {'token': new_session(db, u), 'email': u.email, 'id': u.id}

@app.post('/api/auth/logout')
def logout(user: User = Depends(current_user), authorization: str | None = Header(None), db: DbSession = Depends(get_db)):
    revoke_session(db, authorization)
    return {'ok': True}

@app.get('/api/auth/me')
def me(user: User = Depends(current_user)):
    return {'id': user.id, 'email': user.email}

# --- Event Management ---

@app.get('/api/events')
def events(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    my_event_ids = select(Member.event_id).where(Member.user_id == user.id)
    result = db.scalars(
        select(Event)
        .where((Event.owner_id == user.id) | (Event.id.in_(my_event_ids)))
        .order_by(Event.created_at.desc())
    ).all()
    return [event_out(db, e, user) for e in result]

@app.post('/api/events', status_code=201)
def create_event(body: EventCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = Event(
        id=uid(),
        owner_id=user.id,
        title=body.title.strip(),
        location=body.location.strip(),
        event_date=body.event_date,
        guest_code=secrets.token_urlsafe(24),
        status='live',
        face_enabled=False
    )
    db.add(e)
    db.commit()
    return event_out(db, e, user)

@app.get('/api/events/{eid}')
def event_detail(eid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_member(db, e, user)
    return event_out(db, e, user)

@app.patch('/api/events/{eid}')
def update_event(eid: str, body: EventUpdate, background: BackgroundTasks, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    fields = body.model_dump(exclude_unset=True)
    prior_face = e.face_enabled
    for k, v in fields.items():
        if v is not None:
            setattr(e, k, v.strip() if k in ('title', 'location') else v)
    if prior_face and e.face_enabled is False:
        db.execute(delete(Face).where(Face.event_id == eid))
        db.execute(delete(Job).where(Job.event_id == eid, Job.job_type == 'face_indexing'))
        for p in db.scalars(select(Photo).where(Photo.event_id == eid)):
            p.face_status = 'disabled'
            p.face_count = 0
            p.face_error = ''
    elif not prior_face and e.face_enabled is True:
        pending = db.scalars(select(Photo).where(Photo.event_id == eid)).all()
        for p in pending:
            p.face_status = 'queued'
            p.face_count = 0
            p.face_error = ''
            queue.enqueue_photo_jobs(db, p.id, eid, face_enabled=True, gemini_enabled=False)
    db.commit()
    return event_out(db, e, user)

@app.delete('/api/events/{eid}')
def delete_event(eid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    all_photos = db.scalars(select(Photo).where(Photo.event_id == eid)).all()
    keys = [k for p in all_photos for k in (p.image_key, p.view_key, p.thumb_key)]
    # Keep database records if cloud deletion fails, so deletion can be retried.
    store.delete_many(keys)
    db.execute(delete(Face).where(Face.event_id == eid))
    db.execute(delete(Job).where(Job.event_id == eid))
    db.execute(delete(Photo).where(Photo.event_id == eid))
    db.execute(delete(Member).where(Member.event_id == eid))
    db.execute(delete(Invite).where(Invite.event_id == eid))
    db.delete(e)
    db.commit()
    return {'ok': True, 'deleted_photos': len(all_photos)}

@app.post('/api/events/{eid}/rotate-qr')
def rotate_qr(eid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    e.guest_code = secrets.token_urlsafe(24)
    db.commit()
    return {'guest_code': e.guest_code}

# --- Team & Invites ---

@app.get('/api/events/{eid}/team')
def team(eid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_member(db, e, user)
    members = db.execute(
        select(Member.id, User.email)
        .join(User, Member.user_id == User.id)
        .where(Member.event_id == eid)
    ).all()
    return {
        'owner': db.get(User, e.owner_id).email,
        'photographers': [{'id': m_id, 'email': m_email} for m_id, m_email in members]
    }

@app.delete('/api/events/{eid}/team/{member_id}')
def remove_photographer(eid: str, member_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    member = db.get(Member, member_id)
    if not member or member.event_id != eid:
        raise HTTPException(404, 'Photographer not found')
    db.delete(member)
    db.commit()
    return {'ok': True}

@app.post('/api/events/{eid}/invites', status_code=201)
def invite(eid: str, body: InviteCreate, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    raw = secrets.token_urlsafe(32)
    inv = Invite(
        id=uid(),
        event_id=eid,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        email=str(body.email).lower() if body.email else '',
        expires_at=now() + timedelta(days=7)
    )
    db.add(inv)
    db.commit()
    return {'token': raw, 'expires_in_days': 7, 'event_title': e.title}

@app.get('/api/invites/{token}')
def invite_preview(token: str, db: DbSession = Depends(get_db)):
    inv = db.scalar(select(Invite).where(Invite.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not inv or inv.used_by or inv.expires_at.replace(tzinfo=inv.expires_at.tzinfo or now().tzinfo) < now():
        raise HTTPException(404, 'Invitation expired or already used')
    e = db.get(Event, inv.event_id)
    return {'title': e.title, 'email': inv.email, 'location': e.location}

@app.post('/api/invites/{token}/accept')
def accept_invite(token: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    inv = db.scalar(select(Invite).where(Invite.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not inv or inv.used_by or inv.expires_at.replace(tzinfo=inv.expires_at.tzinfo or now().tzinfo) < now():
        raise HTTPException(404, 'Invitation expired or already used')
    if inv.email and user.email != inv.email:
        raise HTTPException(403, 'This invitation is for a different email address')
    e = get_event(db, inv.event_id)
    existing = db.scalar(select(Member).where(Member.event_id == e.id, Member.user_id == user.id))
    if not existing and e.owner_id != user.id:
        db.add(Member(id=uid(), event_id=e.id, user_id=user.id))
    inv.used_by = user.id
    db.commit()
    return {'event_id': e.id, 'title': e.title}

# --- Photo Processing & Encoding ---

def encode_versions(raw: bytes):
    """Normalize raw photograph into 3 web-optimized JPEG tiers with stripped EXIF."""
    try:
        source = Image.open(io.BytesIO(raw))
        source.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.width * img.height > 80_000_000:
            raise HTTPException(413, 'Image resolution too high')
        img = img.convert('RGB')
    except HTTPException:
        raise
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(415, 'Unsupported or damaged image format. Upload JPEG, PNG or WebP.')

    def jpeg(max_side, quality):
        v = img.copy()
        v.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        v.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
        return buf.getvalue(), v.size

    full, (w, h) = jpeg(4000, 89)
    if STORAGE_DRIVER == 'cloudinary':
        # The Cloudinary Free plan accepts a maximum 10 MiB per image.
        # Preserve quality when possible, but re-encode large DSLR images
        # before reaching the cloud API to avoid partial uploads.
        size_limit = CLOUDINARY_MAX_ASSET_MB * 1024 * 1024
        if len(full) > size_limit:
            for quality in (85, 80, 74, 68, 60):
                full, (w, h) = jpeg(4000, quality)
                if len(full) <= size_limit:
                    break
            else:
                raise HTTPException(
                    413,
                    'Image remains too large for your Cloudinary plan after optimization.'
                )
    view, _ = jpeg(1600, 85)
    thumb, _ = jpeg(650, 80)
    return full, view, thumb, w, h

# --- Photo Upload Routes (Dual Direct & Presigned R2 Flow) ---

@app.post('/api/events/{eid}/photos', status_code=201)
async def upload_photo(
    eid: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    """Direct multipart photo upload.
    
    Used by the DSLR desktop uploader and web fallback. Encodes full, view,
    and thumbnail sizes, stores in R2/local storage, and enqueues durable AI indexing jobs.
    """
    e = get_event(db, eid)
    must_member(db, e, user)
    if e.status != 'live':
        raise HTTPException(403, 'This event is closed to new uploads')

    raw = await file.read(MAX_IMAGE_MB * 1024 * 1024 + 1)
    if len(raw) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(413, f'Maximum upload size is {MAX_IMAGE_MB} MB')
    if not raw:
        raise HTTPException(400, 'Image file is empty')

    checksum = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(Photo).where(Photo.event_id == eid, Photo.sha256 == checksum))
    if existing:
        return {'photo': photo_out(existing), 'duplicate': True}

    full, view, thumb, w, h = encode_versions(raw)
    pid = uid()
    prefix = f'{eid}/{pid}'
    keys = (f'{prefix}/full.jpg', f'{prefix}/view.jpg', f'{prefix}/thumb.jpg')

    try:
        for key, blob in zip(keys, (full, view, thumb)):
            store.put(key, blob)

        p = Photo(
            id=pid,
            event_id=eid,
            uploader_id=user.id,
            sha256=checksum,
            original_name=(file.filename or 'camera.jpg')[:240],
            image_key=keys[0],
            view_key=keys[1],
            thumb_key=keys[2],
            width=w,
            height=h,
            face_status='queued' if e.face_enabled else 'disabled',
            gemini_status='queued' if gemini_ai.is_gemini_available() else 'disabled'
        )
        db.add(p)
        db.commit()
    except IntegrityError:
        db.rollback()
        store.delete_many(list(keys))
        existing = db.scalar(select(Photo).where(Photo.event_id == eid, Photo.sha256 == checksum))
        if existing:
            return {'photo': photo_out(existing), 'duplicate': True}
        raise HTTPException(409, 'Duplicate photo')
    except Exception as ex:
        log.exception('Photo upload storage failure: %s', ex)
        store.delete_many(list(keys))
        raise HTTPException(503, 'Photo storage unavailable; please retry')

    # Enqueue in durable queue (handles both YuNet/SFace and Gemini)
    queue.enqueue_photo_jobs(
        db, pid, eid,
        face_enabled=e.face_enabled,
        gemini_enabled=gemini_ai.is_gemini_available()
    )

    return {'photo': photo_out(p), 'duplicate': False}

@app.post('/api/events/{eid}/photos/request-upload')
def request_presigned_upload(
    eid: str,
    body: PresignedUploadRequest,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    """Generate presigned upload authorization for direct browser-to-R2 upload."""
    e = get_event(db, eid)
    must_member(db, e, user)
    if e.status != 'live':
        raise HTTPException(403, 'This event is closed to new uploads')
    if body.file_size > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(413, f'Maximum file size is {MAX_IMAGE_MB} MB')

    # Local development uses the authenticated multipart endpoint.
    # Do not mint unauthenticated local PUT URLs that bypass photographer roles.
    if not store.is_r2():
        raise HTTPException(409, 'Direct-to-storage upload requires Cloudflare R2; use the authenticated photo upload endpoint locally')

    # Deduplication check
    existing = db.scalar(select(Photo).where(Photo.event_id == eid, Photo.sha256 == body.sha256))
    if existing:
        return {'duplicate': True, 'photo': photo_out(existing)}

    pid = uid()
    prefix = f'{eid}/{pid}'
    full_key = f'{prefix}/full.jpg'
    view_key = f'{prefix}/view.jpg'
    thumb_key = f'{prefix}/thumb.jpg'

    upload_full = store.generate_presigned_upload_url(full_key, content_type='image/jpeg')
    upload_view = store.generate_presigned_upload_url(view_key, content_type='image/jpeg')
    upload_thumb = store.generate_presigned_upload_url(thumb_key, content_type='image/jpeg')

    return {
        'duplicate': False,
        'photo_id': pid,
        'prefix': prefix,
        'uploads': {
            'full': upload_full,
            'view': upload_view,
            'thumb': upload_thumb
        }
    }

@app.post('/api/events/{eid}/photos/confirm-upload')
def confirm_presigned_upload(
    eid: str,
    body: ConfirmUploadRequest,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    """Verify that images were successfully uploaded to R2 and register the database record."""
    e = get_event(db, eid)
    must_member(db, e, user)

    prefix = f'{eid}/{body.photo_id}'
    full_key = f'{prefix}/full.jpg'
    view_key = f'{prefix}/view.jpg'
    thumb_key = f'{prefix}/thumb.jpg'

    # Only Cloudflare R2 supports direct presigned upload confirmation.
    # Cloudinary and local storage use the authenticated multipart endpoint.
    if not store.is_r2():
        raise HTTPException(409, 'Direct-to-storage confirmation requires Cloudflare R2')

    # Verify presence in storage
    head_full = store.head(full_key)
    head_view = store.head(view_key)
    head_thumb = store.head(thumb_key)

    if not head_full['exists'] or not head_view['exists'] or not head_thumb['exists']:
        raise HTTPException(400, 'One or more photo derivatives were not found in storage. Upload failed.')

    try:
        p = Photo(
            id=body.photo_id,
            event_id=eid,
            uploader_id=user.id,
            sha256=body.sha256,
            original_name=body.original_name[:240],
            image_key=full_key,
            view_key=view_key,
            thumb_key=thumb_key,
            width=body.width,
            height=body.height,
            face_status='queued' if e.face_enabled else 'disabled',
            gemini_status='queued' if gemini_ai.is_gemini_available() else 'disabled'
        )
        db.add(p)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Photo).where(Photo.event_id == eid, Photo.sha256 == body.sha256))
        if existing:
            return {'photo': photo_out(existing), 'duplicate': True}
        raise HTTPException(409, 'Duplicate photo entry')

    # Enqueue jobs
    queue.enqueue_photo_jobs(
        db, body.photo_id, eid,
        face_enabled=e.face_enabled,
        gemini_enabled=gemini_ai.is_gemini_available()
    )

    return {'photo': photo_out(p), 'duplicate': False}

# Local development uploads use POST /api/events/{eid}/photos, which
# checks authenticated event membership and validates/normalizes image bytes.

# --- Photo Query & Reprocess ---

@app.get('/api/events/{eid}/photos')
def member_photos(
    eid: str,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    e = get_event(db, eid)
    must_member(db, e, user)
    result = db.scalars(
        select(Photo)
        .where(Photo.event_id == eid)
        .order_by(Photo.created_at.desc(), Photo.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        'photos': [photo_out(p) for p in result],
        'total': db.scalar(select(func.count(Photo.id)).where(Photo.event_id == eid)) or 0
    }

@app.post('/api/events/{eid}/photos/{pid}/reprocess')
def reprocess(eid: str, pid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_member(db, e, user)
    p = db.get(Photo, pid)
    if not p or p.event_id != eid:
        raise HTTPException(404, 'Photo not found')
    p.face_status = 'queued' if e.face_enabled else 'disabled'
    p.face_error = ''
    if gemini_ai.is_gemini_available():
        p.gemini_status = 'queued'
        p.gemini_error = ''
    db.commit()
    queue.enqueue_photo_jobs(
        db, pid, eid,
        face_enabled=e.face_enabled,
        gemini_enabled=gemini_ai.is_gemini_available()
    )
    return {'ok': True}

@app.delete('/api/events/{eid}/photos/{pid}')
def delete_photo(eid: str, pid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    p = db.get(Photo, pid)
    if not p or p.event_id != eid:
        raise HTTPException(404, 'Photo not found')
    keys = (p.image_key, p.view_key, p.thumb_key)
    store.delete_many(list(keys))
    db.execute(delete(Face).where(Face.photo_id == pid))
    db.execute(delete(Job).where(Job.photo_id == pid))
    db.delete(p)
    db.commit()
    return {'ok': True}

@app.get('/api/events/{eid}/clusters')
def clusters(eid: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    e = get_event(db, eid)
    must_owner(db, e, user)
    if not e.face_enabled:
        return {'clusters': [], 'total_faces': 0}
    rows = db.execute(
        select(Face.cluster_id, func.count(Face.id))
        .where(Face.event_id == eid)
        .group_by(Face.cluster_id)
        .order_by(func.count(Face.id).desc())
    ).all()
    return {
        'clusters': [{'id': key, 'face_count': count} for key, count in rows],
        'total_faces': sum(c for _, c in rows)
    }

# --- Guest Gallery Routes ---

@app.get('/api/g/{code}')
def guest_event(code: str, db: DbSession = Depends(get_db)):
    e = get_guest_event(db, code)
    return {
        'title': e.title,
        'location': e.location,
        'event_date': e.event_date,
        'status': e.status,
        'face_enabled': e.face_enabled,
        'downloads_enabled': e.downloads_enabled,
        'photo_count': db.scalar(select(func.count(Photo.id)).where(Photo.event_id == e.id)) or 0
    }

@app.get('/api/g/{code}/photos')
def guest_photos(
    code: str,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DbSession = Depends(get_db)
):
    e = get_guest_event(db, code)
    rows = db.scalars(
        select(Photo)
        .where(Photo.event_id == e.id)
        .order_by(Photo.created_at.desc(), Photo.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        'photos': [photo_out(p) for p in rows],
        'total': db.scalar(select(func.count(Photo.id)).where(Photo.event_id == e.id)) or 0
    }

# --- Image Serving (Presigned R2 302 Redirect or Local Stream) ---

def image_response(key: str, download: bool = False, filename: str = 'photo.jpg'):
    """Serve images: 302 redirect to Cloudflare R2 presigned URL when in cloud mode,
    or stream directly from disk when in local development mode.
    """
    if store.is_r2():
        # Generate 15-minute time-limited presigned download URL
        url = store.generate_presigned_download_url(
            key,
            expires_in=900,
            filename=filename if download else None
        )
        if url:
            return RedirectResponse(
                url=url,
                status_code=302,
                headers={
                    'Cache-Control': 'private, max-age=120',
                    'X-Robots-Tag': 'noindex, nofollow'
                }
            )
    # Local fallback
    data = store.get(key)
    headers = {
        'Cache-Control': 'private, max-age=120',
        'X-Robots-Tag': 'noindex, nofollow',
        'Content-Security-Policy': "default-src 'none'"
    }
    if download:
        headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return Response(content=data, media_type='image/jpeg', headers=headers)

@app.get('/api/g/{code}/photos/{pid}/image')
def guest_image(
    code: str,
    pid: str,
    size: Literal['thumb', 'view', 'full'] = 'view',
    db: DbSession = Depends(get_db)
):
    e = get_guest_event(db, code)
    p = db.get(Photo, pid)
    if not p or p.event_id != e.id:
        raise HTTPException(404, 'Photo not found')
    if size == 'full' and not e.downloads_enabled:
        raise HTTPException(403, 'Downloads are disabled for this event')
    key = {'thumb': p.thumb_key, 'view': p.view_key, 'full': p.image_key}[size]
    return image_response(key, download=(size == 'full'), filename=f'clickbook-{p.id}.jpg')

@app.get('/api/events/{eid}/photos/{pid}/image')
def team_image(
    eid: str,
    pid: str,
    size: Literal['thumb', 'view', 'full'] = 'full',
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    e = get_event(db, eid)
    must_member(db, e, user)
    p = db.get(Photo, pid)
    if not p or p.event_id != eid:
        raise HTTPException(404, 'Photo not found')
    key = {'thumb': p.thumb_key, 'view': p.view_key, 'full': p.image_key}[size]
    return image_response(key, download=(size == 'full'), filename=f'clickbook-{p.id}.jpg')

# --- Face Discovery Routes ---

@app.get('/api/g/{code}/photos/{pid}/faces')
def photo_face_boxes(code: str, pid: str, consent: bool = False, db: DbSession = Depends(get_db)):
    e = get_guest_event(db, code)
    if not e.face_enabled:
        raise HTTPException(403, 'Face search is disabled for this event')
    if not consent:
        raise HTTPException(400, 'Explicit face-search consent is required')
    p = db.get(Photo, pid)
    if not p or p.event_id != e.id:
        raise HTTPException(404, 'Photo not found')
    if p.face_status != 'done':
        raise HTTPException(409, 'Face analysis for this photo is not ready yet')
    rows = db.scalars(select(Face).where(Face.photo_id == pid)).all()
    return {'faces': [{'id': f.id, 'box': f.bbox} for f in rows]}

def find_matches(db: DbSession, e: Event, vector: list):
    faces = db.scalars(select(Face).where(Face.event_id == e.id)).all()
    ranked = face_ai.match_photos(vector, faces)
    photos = db.scalars(select(Photo).where(Photo.id.in_([p_id for p_id, _ in ranked]))).all() if ranked else []
    lookup = {p.id: p for p in photos}
    return {
        'matches': [
            {'photo': photo_out(lookup[pid]), 'similarity': round(score, 3)}
            for pid, score in ranked if pid in lookup
        ],
        'total': len(ranked),
        'note': 'Face matches are statistical estimates and may contain inaccuracies.'
    }

@app.post('/api/g/{code}/find-by-photo')
def find_by_photo(code: str, body: FacePoint, request: Request, db: DbSession = Depends(get_db)):
    e = get_guest_event(db, code)
    if not e.face_enabled:
        raise HTTPException(403, 'Face search is disabled for this event')
    if not body.consent:
        raise HTTPException(400, 'Please accept face-search consent')
    rate_limit(request, code)
    p = db.get(Photo, body.photo_id)
    if not p or p.event_id != e.id:
        raise HTTPException(404, 'Photo not found')
    if p.face_status != 'done':
        raise HTTPException(409, 'Face analysis is still processing')
    faces = db.scalars(select(Face).where(Face.photo_id == p.id)).all()
    if not faces:
        raise HTTPException(422, 'No face detected in this photo')

    def distance(f):
        x, y, w, h = f.bbox
        if x - 0.015 <= body.x <= x + w + 0.015 and y - 0.015 <= body.y <= y + h + 0.015:
            return 0
        cx = x + w / 2
        cy = y + h / 2
        return (cx - body.x) ** 2 + (cy - body.y) ** 2

    chosen = min(faces, key=distance)
    if distance(chosen) > 0.0025:
        raise HTTPException(422, 'Select closer to a detected face')
    return find_matches(db, e, chosen.embedding)

@app.post('/api/g/{code}/find-by-selfie')
async def find_by_selfie(
    code: str,
    request: Request,
    file: UploadFile = File(...),
    consent: bool = False,
    db: DbSession = Depends(get_db)
):
    e = get_guest_event(db, code)
    if not e.face_enabled:
        raise HTTPException(403, 'Face search is disabled for this event')
    if not consent:
        raise HTTPException(400, 'Please accept face-search consent')
    rate_limit(request, code)
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, 'Selfie must be smaller than 8 MB')
    _, view, _, _, _ = encode_versions(raw)

    # CRITICAL: Guest selfies are strictly kept in-memory and NEVER saved to disk, DB, logs, or Gemini.
    try:
        detected = face_ai.extract_faces(view)
    except RuntimeError:
        raise HTTPException(503, 'Face AI models are not installed on this server')

    if not detected:
        raise HTTPException(422, 'No face detected. Please try a brighter, front-facing selfie.')
    if len(detected) > 1:
        raise HTTPException(422, 'Please take a selfie with only your face visible.')
    return find_matches(db, e, detected[0]['vector'])

# --- Semantic Search (Gemini Metadata) ---

@app.get('/api/g/{code}/photos/search')
def guest_semantic_search(
    code: str,
    q: str = Query(min_length=1, max_length=100),
    db: DbSession = Depends(get_db)
):
    """Search event photos by keyword, category, tag or description."""
    e = get_guest_event(db, code)
    search_term = q.strip().lower()
    
    # Query photos matching tags, caption, moment type, description or original name
    query = (
        select(Photo)
        .where(
            Photo.event_id == e.id,
            or_(
                func.lower(Photo.gemini_moment_type).contains(search_term),
                func.lower(Photo.gemini_caption).contains(search_term),
                func.lower(Photo.gemini_description).contains(search_term),
                func.lower(Photo.gemini_context).contains(search_term),
                func.lower(Photo.original_name).contains(search_term)
            )
        )
        .order_by(Photo.created_at.desc())
        .limit(60)
    )
    results = db.scalars(query).all()
    return {
        'query': q,
        'photos': [photo_out(p) for p in results],
        'total': len(results)
    }

@app.get('/api/events/{eid}/photos/search')
def team_semantic_search(
    eid: str,
    q: str = Query(min_length=1, max_length=100),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db)
):
    e = get_event(db, eid)
    must_member(db, e, user)
    search_term = q.strip().lower()
    query = (
        select(Photo)
        .where(
            Photo.event_id == eid,
            or_(
                func.lower(Photo.gemini_moment_type).contains(search_term),
                func.lower(Photo.gemini_caption).contains(search_term),
                func.lower(Photo.gemini_description).contains(search_term),
                func.lower(Photo.gemini_context).contains(search_term),
                func.lower(Photo.original_name).contains(search_term)
            )
        )
        .order_by(Photo.created_at.desc())
        .limit(60)
    )
    results = db.scalars(query).all()
    return {
        'query': q,
        'photos': [photo_out(p) for p in results],
        'total': len(results)
    }

# --- Real-Time Gallery SSE Stream ---

@app.get('/api/g/{code}/stream')
async def updates(code: str, request: Request):
    """Server-Sent Events stream for live gallery refreshes without polling."""
    with SessionLocal() as db:
        get_guest_event(db, code)

    async def generate():
        import asyncio
        last = None
        for _ in range(13):
            if await request.is_disconnected():
                break
            with SessionLocal() as db:
                e = get_guest_event(db, code)
                value = db.scalar(select(func.count(Photo.id)).where(Photo.event_id == e.id)) or 0
                face_progress = db.scalar(
                    select(func.count(Photo.id)).where(Photo.event_id == e.id, Photo.face_status == 'done')
                ) or 0
                marker = f'{value}:{face_progress}:{e.face_enabled}:{e.downloads_enabled}'
            if marker != last:
                yield f'event: update\ndata: {json.dumps({"count": value, "processed": face_progress})}\n\n'
                last = marker
            else:
                yield ': ping\n\n'
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'X-Robots-Tag': 'noindex'
        }
    )

# --- Frontend SPA Static Serving ---

import os
from pathlib import Path
SITE_DIR = Path(os.environ.get('CLICKBOOK_FRONTEND_DIST', '/site'))
if SITE_DIR.is_dir() and (SITE_DIR / 'index.html').is_file():
    if (SITE_DIR / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=str(SITE_DIR / 'assets')), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def spa(path: str):
        if path.startswith('api/'):
            raise HTTPException(404, 'API endpoint not found')
        # Do not serve arbitrary filesystem paths; only SPA fallback and static assets
        if path and '.' in Path(path).name:
            asset_path = SITE_DIR / path
            if asset_path.is_file():
                return FileResponse(asset_path)
            raise HTTPException(404, 'Static asset not found')
        return FileResponse(
            SITE_DIR / 'index.html',
            headers={'Cache-Control': 'no-cache', 'X-Robots-Tag': 'noindex, nofollow'}
            if path.startswith('g/') else {'Cache-Control': 'no-cache'}
        )
