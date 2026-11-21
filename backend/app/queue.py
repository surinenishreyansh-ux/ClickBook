"""Persistent, durable background job queue backed by PostgreSQL / SQLite.

Survives backend restarts, handles transient failures with exponential backoff,
prevents race conditions with atomic job claiming, and separates CPU-heavy
vision/AI tasks from the FastAPI request/response path.
"""

import datetime as dt
from datetime import timedelta
import logging
import threading
import time
from sqlalchemy import select, update, delete, or_, and_
from sqlalchemy.orm import Session as DbSession
from .db import SessionLocal, Job, Photo, Event, Face, uid, now
from .storage import store
from . import face_ai
from . import gemini_ai

log = logging.getLogger('clickbook.queue')

LEASE_DURATION = timedelta(seconds=120)

def enqueue_photo_jobs(db: DbSession, photo_id: str, event_id: str, face_enabled: bool, gemini_enabled: bool):
    """Enqueue background indexing jobs for an uploaded photo."""
    if face_enabled:
        existing = db.scalar(
            select(Job).where(Job.photo_id == photo_id, Job.job_type == 'face_indexing')
        )
        if not existing:
            db.add(Job(
                id=uid(),
                event_id=event_id,
                photo_id=photo_id,
                job_type='face_indexing',
                status='pending',
                scheduled_at=now()
            ))
        elif existing.status in ('failed', 'completed'):
            existing.status = 'pending'
            existing.error = ''
            existing.attempts = 0
            existing.scheduled_at = now()

    if gemini_enabled and gemini_ai.is_gemini_available():
        existing = db.scalar(
            select(Job).where(Job.photo_id == photo_id, Job.job_type == 'gemini_analysis')
        )
        if not existing:
            db.add(Job(
                id=uid(),
                event_id=event_id,
                photo_id=photo_id,
                job_type='gemini_analysis',
                status='pending',
                scheduled_at=now()
            ))
        elif existing.status in ('failed', 'completed'):
            existing.status = 'pending'
            existing.error = ''
            existing.attempts = 0
            existing.scheduled_at = now()

    db.commit()

def claim_next_jobs(db: DbSession, limit: int = 5) -> list[str]:
    """Atomically claim a batch of pending or expired jobs.
    
    Uses PostgreSQL FOR UPDATE SKIP LOCKED if supported, with safe atomic fallback.
    """
    current_time = now()
    
    # Identify runnable candidates
    query = (
        select(Job.id)
        .where(
            or_(
                Job.status == 'pending',
                and_(Job.status == 'processing', Job.locked_until < current_time)
            ),
            Job.scheduled_at <= current_time
        )
        .order_by(Job.scheduled_at.asc(), Job.created_at.asc())
        .limit(limit)
    )

    try:
        # Check dialect for PostgreSQL SKIP LOCKED
        dialect_name = db.bind.dialect.name if db.bind else 'sqlite'
        if dialect_name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
            candidate_ids = db.scalars(query).all()
        else:
            candidate_ids = db.scalars(query).all()
    except Exception:
        candidate_ids = db.scalars(query).all()

    claimed_ids = []
    for jid in candidate_ids:
        # Atomically update to processing status
        res = db.execute(
            update(Job)
            .where(
                Job.id == jid,
                or_(
                    Job.status == 'pending',
                    and_(Job.status == 'processing', Job.locked_until < current_time)
                )
            )
            .values(
                status='processing',
                locked_until=current_time + LEASE_DURATION,
                attempts=Job.attempts + 1,
                updated_at=current_time
            )
        )
        if res.rowcount == 1:
            claimed_ids.append(jid)
            
    db.commit()
    return claimed_ids

def execute_job(job_id: str):
    """Execute a single claimed job to completion or handle retries on error."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status != 'processing':
            return
        
        photo = db.get(Photo, job.photo_id)
        event = db.get(Event, job.event_id)
        if not photo or not event:
            # Referenced record was deleted
            db.delete(job)
            db.commit()
            return

        job_type = job.job_type
        view_key = photo.view_key
        attempts = job.attempts
        max_attempts = job.max_attempts

    try:
        image_bytes = store.get(view_key)

        if job_type == 'face_indexing':
            if not event.face_enabled:
                with SessionLocal() as db:
                    p = db.get(Photo, photo.id)
                    if p: p.face_status = 'disabled'
                    j = db.get(Job, job_id)
                    if j: j.status = 'completed'; j.error = 'Face discovery disabled for event'
                    db.commit()
                return

            # Extract faces locally with OpenCV Zoo YuNet & SFace
            faces = face_ai.extract_faces(image_bytes)

            with SessionLocal() as db:
                p = db.get(Photo, photo.id)
                e = db.get(Event, event.id)
                if not p or not e or not e.face_enabled:
                    if p: p.face_status = 'disabled'
                    j = db.get(Job, job_id)
                    if j: j.status = 'completed'
                    db.commit()
                    return

                # Replace any previous faces for this photo
                db.execute(delete(Face).where(Face.photo_id == p.id))
                previous_faces = db.scalars(select(Face).where(Face.event_id == e.id)).all()

                for item in faces:
                    cluster = face_ai.choose_cluster(item['vector'], previous_faces)
                    f = Face(
                        id=uid(),
                        photo_id=p.id,
                        event_id=e.id,
                        bbox=item['box'],
                        embedding=item['vector'],
                        cluster_id=cluster
                    )
                    db.add(f)
                    previous_faces.append(f)

                p.face_count = len(faces)
                p.face_status = 'done'
                p.face_error = ''

                j = db.get(Job, job_id)
                if j:
                    j.status = 'completed'
                    j.error = ''
                db.commit()

        elif job_type == 'gemini_analysis':
            metadata = gemini_ai.analyze_photo(image_bytes)
            with SessionLocal() as db:
                p = db.get(Photo, photo.id)
                j = db.get(Job, job_id)
                if p:
                    if metadata:
                        p.gemini_status = 'done'
                        p.gemini_description = metadata.get('description')
                        p.gemini_context = metadata.get('context')
                        p.gemini_moment_type = metadata.get('moment_type')
                        p.gemini_tags = metadata.get('tags')
                        p.gemini_caption = metadata.get('caption')
                        p.gemini_error = ''
                    else:
                        p.gemini_status = 'unavailable'
                        p.gemini_error = 'Gemini API unavailable or quota reached'
                if j:
                    j.status = 'completed'
                db.commit()

    except Exception as exc:
        log.exception('Job execution error for job %s (%s): %s', job_id, job_type, exc)
        with SessionLocal() as db:
            j = db.get(Job, job_id)
            p = db.get(Photo, photo.id)
            err_msg = str(exc)[:400]
            if j:
                if attempts < max_attempts:
                    # Exponential backoff retry: 5s, 20s, 60s
                    backoff_secs = 5 * (4 ** (attempts - 1))
                    j.status = 'pending'
                    j.error = f"Attempt {attempts} failed: {err_msg}"
                    j.scheduled_at = now() + timedelta(seconds=backoff_secs)
                    log.info('Scheduled retry for job %s in %ds', job_id, backoff_secs)
                else:
                    j.status = 'failed'
                    j.error = f"Max attempts reached. Last error: {err_msg}"
            if p:
                if job_type == 'face_indexing':
                    p.face_status = 'failed'
                    p.face_error = err_msg[:240]
                elif job_type == 'gemini_analysis':
                    p.gemini_status = 'failed'
                    p.gemini_error = err_msg[:240]
            db.commit()

# Durable worker loop
_worker_stop = threading.Event()
_worker_thread = None

def worker_loop():
    """Background worker daemon processing persistent jobs."""
    log.info('ClickBook persistent background job processor started.')
    while not _worker_stop.wait(2.5):
        try:
            with SessionLocal() as db:
                claimed_ids = claim_next_jobs(db, limit=4)
            for jid in claimed_ids:
                if _worker_stop.is_set():
                    break
                execute_job(jid)
        except Exception:
            log.exception('Unexpected error in worker loop; recovering...')
            time.sleep(1)

def start_worker():
    global _worker_thread
    _worker_stop.clear()
    # Reset any stale processing jobs from previous crashes
    with SessionLocal() as db:
        db.execute(
            update(Job)
            .where(Job.status == 'processing')
            .values(status='pending', scheduled_at=now())
        )
        db.execute(
            update(Photo)
            .where(Photo.face_status == 'processing')
            .values(face_status='queued')
        )
        db.commit()
    _worker_thread = threading.Thread(target=worker_loop, daemon=True, name='clickbook-job-worker')
    _worker_thread.start()

def stop_worker():
    global _worker_thread
    _worker_stop.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
        _worker_thread = None
