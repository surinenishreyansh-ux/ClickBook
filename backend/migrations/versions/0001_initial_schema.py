"""Initial ClickBook production schema with Neon PostgreSQL and SQLite support

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-21 11:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('password_salt', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # 2. sessions
    op.create_table(
        'sessions',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])

    # 3. events
    op.create_table(
        'events',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('owner_id', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('location', sa.String(length=150), nullable=False, server_default=''),
        sa.Column('event_date', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='live'),
        sa.Column('guest_code', sa.String(length=64), nullable=False),
        sa.Column('face_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('downloads_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_owner_id', 'events', ['owner_id'])
    op.create_index('ix_events_guest_code', 'events', ['guest_code'], unique=True)

    # 4. members
    op.create_table(
        'members',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'user_id', name='uq_members_event_user')
    )
    op.create_index('ix_members_event_id', 'members', ['event_id'])
    op.create_index('ix_members_user_id', 'members', ['user_id'])

    # 5. invites
    op.create_table(
        'invites',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_by', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_invites_token_hash')
    )
    op.create_index('ix_invites_event_id', 'invites', ['event_id'])

    # 6. photos
    op.create_table(
        'photos',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('uploader_id', sa.String(length=32), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('original_name', sa.String(length=240), nullable=False),
        sa.Column('image_key', sa.String(length=256), nullable=False),
        sa.Column('view_key', sa.String(length=256), nullable=False),
        sa.Column('thumb_key', sa.String(length=256), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('face_status', sa.String(length=16), nullable=False, server_default='queued'),
        sa.Column('face_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('face_error', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('gemini_status', sa.String(length=16), nullable=False, server_default='disabled'),
        sa.Column('gemini_description', sa.Text(), nullable=True),
        sa.Column('gemini_context', sa.String(length=120), nullable=True),
        sa.Column('gemini_moment_type', sa.String(length=64), nullable=True),
        sa.Column('gemini_tags', sa.JSON(), nullable=True),
        sa.Column('gemini_caption', sa.String(length=300), nullable=True),
        sa.Column('gemini_error', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploader_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'sha256', name='uq_photos_event_sha256')
    )
    op.create_index('ix_photos_event_id', 'photos', ['event_id'])
    op.create_index('ix_photo_event_time', 'photos', ['event_id', 'created_at'])

    # 7. faces
    op.create_table(
        'faces',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('photo_id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('bbox', sa.JSON(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=False),
        sa.Column('cluster_id', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['photo_id'], ['photos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_faces_photo_id', 'faces', ['photo_id'])
    op.create_index('ix_faces_event_id', 'faces', ['event_id'])
    op.create_index('ix_faces_cluster_id', 'faces', ['cluster_id'])
    op.create_index('ix_face_event_cluster', 'faces', ['event_id', 'cluster_id'])

    # 8. jobs (Persistent Background Job Queue)
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('photo_id', sa.String(length=32), nullable=False),
        sa.Column('job_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('error', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['photo_id'], ['photos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_event_id', 'jobs', ['event_id'])
    op.create_index('ix_jobs_photo_id', 'jobs', ['photo_id'])
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_scheduled_at', 'jobs', ['scheduled_at'])
    op.create_index('ix_job_status_scheduled', 'jobs', ['status', 'scheduled_at'])
    op.create_index('ix_job_photo_type', 'jobs', ['photo_id', 'job_type'])

def downgrade() -> None:
    op.drop_table('jobs')
    op.drop_table('faces')
    op.drop_table('photos')
    op.drop_table('invites')
    op.drop_table('members')
    op.drop_table('events')
    op.drop_table('sessions')
    op.drop_table('users')
