import datetime as dt
import uuid
import logging
from sqlalchemy import (
    create_engine, String, ForeignKey, Integer, Boolean, DateTime, Text,
    UniqueConstraint, Index, JSON, event
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import QueuePool
from .config import (
    DATABASE_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE
)

log = logging.getLogger('clickbook.db')

class Base(DeclarativeBase):
    pass

def uid():
    return uuid.uuid4().hex

def now():
    return dt.datetime.now(dt.timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(150), default='')
    event_date: Mapped[str] = mapped_column(String(32), default='')
    status: Mapped[str] = mapped_column(String(12), default='live')
    guest_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    face_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    downloads_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Member(Base):
    __tablename__ = 'members'
    __table_args__ = (UniqueConstraint('event_id', 'user_id'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Invite(Base):
    __tablename__ = 'invites'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254), default='')
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)

class Photo(Base):
    __tablename__ = 'photos'
    __table_args__ = (
        UniqueConstraint('event_id', 'sha256'),
        Index('ix_photo_event_time', 'event_id', 'created_at')
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    uploader_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    sha256: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str] = mapped_column(String(240))
    image_key: Mapped[str] = mapped_column(String(256))
    view_key: Mapped[str] = mapped_column(String(256))
    thumb_key: Mapped[str] = mapped_column(String(256))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Face AI indexing metadata
    face_status: Mapped[str] = mapped_column(String(16), default='queued')
    face_count: Mapped[int] = mapped_column(Integer, default=0)
    face_error: Mapped[str] = mapped_column(String(300), default='')
    # Gemini Multimodal AI metadata
    gemini_status: Mapped[str] = mapped_column(String(16), default='disabled')
    gemini_description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    gemini_context: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    gemini_moment_type: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    gemini_tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    gemini_caption: Mapped[str | None] = mapped_column(String(300), nullable=True, default=None)
    gemini_error: Mapped[str | None] = mapped_column(String(300), nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Face(Base):
    __tablename__ = 'faces'
    __table_args__ = (Index('ix_face_event_cluster', 'event_id', 'cluster_id'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    photo_id: Mapped[str] = mapped_column(ForeignKey('photos.id', ondelete='CASCADE'), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    bbox: Mapped[list] = mapped_column(JSON)
    embedding: Mapped[list] = mapped_column(JSON)
    cluster_id: Mapped[str] = mapped_column(String(32), index=True)

class Job(Base):
    __tablename__ = 'jobs'
    __table_args__ = (
        Index('ix_job_status_scheduled', 'status', 'scheduled_at'),
        Index('ix_job_photo_type', 'photo_id', 'job_type'),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey('photos.id', ondelete='CASCADE'), index=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True) # 'face_indexing' | 'gemini_analysis'
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True) # pending, processing, completed, failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str] = mapped_column(String(500), default='')
    scheduled_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

# Engine configuration supporting PostgreSQL connection pooling & SQLite fallback
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(
        DATABASE_URL,
        connect_args={'check_same_thread': False, 'timeout': 30},
        pool_pre_ping=True
    )
    @event.listens_for(engine, 'connect')
    def enable_sqlite(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()
else:
    # Neon PostgreSQL connection pool
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def init_db():
    """Ensure all database tables exist. Compatible with SQLite and PostgreSQL."""
    try:
        Base.metadata.create_all(engine)
        log.info('Database tables verified/initialized.')
    except Exception as e:
        log.exception('Database initialization error: %s', e)
        raise

def get_db():
    with SessionLocal() as db:
        yield db
