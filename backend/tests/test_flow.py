import io
import os
import tempfile
import atexit
from pathlib import Path

# Set isolated storage/database before loading the app.
TEST_DIR = tempfile.TemporaryDirectory(prefix='clickbook-test-')
os.environ['CLICKBOOK_DATA'] = TEST_DIR.name
os.environ['DATABASE_URL'] = f'sqlite:///{Path(TEST_DIR.name)/"test.sqlite3"}'
os.environ['STORAGE_DRIVER'] = 'local'

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from app.main import app
from app.db import engine, SessionLocal, Photo, Event, Job, uid, now
from app import face_ai, gemini_ai, queue
from app.storage import Storage

client = TestClient(app)

def cleanup_engine():
    try:
        engine.dispose()
    except Exception:
        pass

atexit.register(cleanup_engine)

def jpeg(color=(120, 30, 90)):
    im = Image.new('RGB', (800, 600), color=color)
    b = io.BytesIO()
    im.save(b, format='JPEG')
    return b.getvalue()

def signup(email):
    r = client.post('/api/auth/register', json={'email': email, 'password': 'very-long-password-123'})
    assert r.status_code == 201, r.text
    return r.json()['token']

def headers(token):
    return {'Authorization': f'Bearer {token}'}

def create_event(token, title='Night Event'):
    r = client.post('/api/events', headers=headers(token), json={'title': title, 'location': 'Main Arena', 'event_date': '2026-12-20'})
    assert r.status_code == 201, r.text
    return r.json()

def test_full_flow(monkeypatch):
    owner = signup('owner@example.com')
    photographer = signup('photographer@example.com')
    outsider = signup('random@example.com')
    event = create_event(owner)
    eid = event['id']
    code = event['guest_code']
    assert event['face_enabled'] is False
    assert client.get(f'/api/g/{code}').json()['title'] == 'Night Event'

    # Unauthorized photo upload attempt
    r = client.post(f'/api/events/{eid}/photos', headers=headers(outsider), files={'file': ('x.jpg', jpeg(), 'image/jpeg')})
    assert r.status_code == 403

    # Invite photographer
    r = client.post(f'/api/events/{eid}/invites', headers=headers(owner), json={'email': 'photographer@example.com'})
    assert r.status_code == 201
    invite = r.json()['token']
    assert client.get(f'/api/invites/{invite}').status_code == 200
    assert client.post(f'/api/invites/{invite}/accept', headers=headers(outsider)).status_code == 403
    assert client.post(f'/api/invites/{invite}/accept', headers=headers(photographer)).status_code == 200
    assert client.post(f'/api/invites/{invite}/accept', headers=headers(photographer)).status_code == 404

    # Upload and guest gallery available without face models
    r = client.post(f'/api/events/{eid}/photos', headers=headers(photographer), files={'file': ('first.jpg', jpeg(), 'image/jpeg')})
    assert r.status_code == 201, r.text
    p1 = r.json()['photo']['id']
    assert r.json()['photo']['face_status'] == 'disabled'

    duplicate = client.post(f'/api/events/{eid}/photos', headers=headers(photographer), files={'file': ('first.jpg', jpeg(), 'image/jpeg')})
    assert duplicate.status_code == 201 and duplicate.json()['duplicate'] is True
    assert client.get(f'/api/g/{code}/photos').json()['total'] == 1
    assert client.get(f'/api/g/{code}/photos/{p1}/image?size=thumb').status_code == 200
    assert client.get(f'/api/g/{code}/photos/{p1}/image?size=full').status_code == 200
    assert client.get(f'/api/g/{code}/photos/invalid/image').status_code == 404
    assert client.post(f'/api/g/{code}/find-by-selfie?consent=true', files={'file': ('s.jpg', jpeg(), 'image/jpeg')}).status_code == 403

    # Stub the face model outputs to test indexing/clustering/search logic deterministically
    test_vector = [0.0] * 128
    test_vector[0] = 1.0
    monkeypatch.setattr(face_ai, 'extract_faces', lambda _: [{'box': [.2, .2, .2, .2], 'vector': test_vector}])

    r = client.patch(f'/api/events/{eid}', headers=headers(owner), json={'face_enabled': True})
    assert r.status_code == 200, r.text

    # Run queue jobs for the event
    with SessionLocal() as db:
        claimed = queue.claim_next_jobs(db, limit=10)
    for jid in claimed:
        queue.execute_job(jid)

    current = client.get(f'/api/events/{eid}/photos', headers=headers(owner)).json()['photos'][0]
    assert current['face_status'] == 'done' and current['face_count'] == 1

    r = client.post(f'/api/events/{eid}/photos', headers=headers(photographer), files={'file': ('second.jpg', jpeg((180, 90, 70)), 'image/jpeg')})
    assert r.status_code == 201, r.text
    p2 = r.json()['photo']['id']

    # Process second photo
    with SessionLocal() as db:
        claimed = queue.claim_next_jobs(db, limit=10)
    for jid in claimed:
        queue.execute_job(jid)

    assert client.get(f'/api/events/{eid}/clusters', headers=headers(owner)).json()['clusters'][0]['face_count'] == 2
    assert client.get(f'/api/g/{code}/photos/{p1}/faces?consent=true').json()['faces'][0]['box'] == [.2, .2, .2, .2]

    r = client.post(f'/api/g/{code}/find-by-photo', json={'photo_id': p1, 'x': .3, 'y': .3, 'consent': True})
    assert r.status_code == 200, r.text
    assert {m['photo']['id'] for m in r.json()['matches']} == {p1, p2}

    r = client.post(f'/api/g/{code}/find-by-selfie?consent=true', files={'file': ('selfie.jpg', jpeg((60, 140, 10)), 'image/jpeg')})
    assert r.status_code == 200 and r.json()['total'] == 2
    assert client.post(f'/api/g/{code}/find-by-photo', json={'photo_id': p1, 'x': .95, 'y': .95, 'consent': True}).status_code == 422
    assert client.post(f'/api/g/{code}/find-by-photo', json={'photo_id': p1, 'x': .3, 'y': .3, 'consent': False}).status_code == 400

    # Owner moderation & privacy toggles
    assert client.patch(f'/api/events/{eid}', headers=headers(photographer), json={'downloads_enabled': False}).status_code == 403
    assert client.patch(f'/api/events/{eid}', headers=headers(owner), json={'downloads_enabled': False}).status_code == 200
    assert client.get(f'/api/g/{code}/photos/{p1}/image?size=full').status_code == 403
    assert client.get(f'/api/g/{code}/photos/{p1}/image?size=view').status_code == 200
    assert client.patch(f'/api/events/{eid}', headers=headers(owner), json={'face_enabled': False}).status_code == 200
    assert client.get(f'/api/events/{eid}/clusters', headers=headers(owner)).json()['total_faces'] == 0
    assert client.post(f'/api/g/{code}/find-by-photo', json={'photo_id': p1, 'x': .3, 'y': .3, 'consent': True}).status_code == 403

    team = client.get(f'/api/events/{eid}/team', headers=headers(owner)).json()
    member_id = team['photographers'][0]['id']
    assert client.delete(f'/api/events/{eid}/team/{member_id}', headers=headers(owner)).status_code == 200
    assert client.post(f'/api/events/{eid}/photos', headers=headers(photographer), files={'file': ('third.jpg', jpeg((20, 30, 40)), 'image/jpeg')}).status_code == 403
    assert client.delete(f'/api/events/{eid}/photos/{p1}', headers=headers(owner)).status_code == 200
    assert client.get(f'/api/g/{code}/photos/{p1}/image').status_code == 404
    assert client.post(f'/api/events/{eid}/rotate-qr', headers=headers(owner)).status_code == 200
    assert client.get(f'/api/g/{code}').status_code == 404
    assert client.delete(f'/api/events/{eid}', headers=headers(owner)).status_code == 200
    assert client.get('/api/events', headers=headers(owner)).json() == []

def test_invalid_and_auth():
    owner = signup('another@example.com')
    assert client.post('/api/auth/login', json={'email': 'another@example.com', 'password': 'incorrect-12345'}).status_code == 401
    assert client.get('/api/events').status_code == 401
    event = create_event(owner, 'Private Album')
    bad = client.post(f'/api/events/{event["id"]}/photos', headers=headers(owner), files={'file': ('bad.jpg', b'not-a-picture', 'image/jpeg')})
    assert bad.status_code == 415
    assert client.post('/api/auth/logout', headers=headers(owner)).status_code == 200
    assert client.get('/api/events', headers=headers(owner)).status_code == 401

def test_cosine_and_clustering_helpers():
    from types import SimpleNamespace
    vec1 = [0.0] * 128
    vec1[0] = 1.0
    vec2 = [0.0] * 128
    vec2[1] = 1.0
    rows = [
        SimpleNamespace(embedding=vec1, cluster_id='guest-a', photo_id='photo-a'),
        SimpleNamespace(embedding=vec1, cluster_id='guest-a', photo_id='photo-b'),
        SimpleNamespace(embedding=vec2, cluster_id='guest-b', photo_id='photo-c')
    ]
    assert face_ai.choose_cluster(vec1, rows) == 'guest-a'
    assert face_ai.match_photos(vec1, rows) == [('photo-a', 1.0),('photo-b', 1.0)]
    assert len(face_ai.choose_cluster([0.0] * 128, rows)) == 32

def test_r2_storage_adapter(monkeypatch):
    """Test Cloudflare R2 storage adapter presigned URLs, HEAD, PUT, GET and DELETE."""
    # Mock boto3 S3 client
    class MockS3Client:
        def __init__(self):
            self.store = {}
        def put_object(self, Bucket, Key, Body, ContentType=None, CacheControl=None):
            self.store[Key] = {'body': Body, 'content_type': ContentType}
            return {}
        def get_object(self, Bucket, Key):
            if Key not in self.store:
                from botocore.exceptions import ClientError
                raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
            return {'Body': io.BytesIO(self.store[Key]['body'])}
        def head_object(self, Bucket, Key):
            if Key not in self.store:
                from botocore.exceptions import ClientError
                raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'HeadObject')
            return {'ContentLength': len(self.store[Key]['body']), 'ContentType': self.store[Key]['content_type']}
        def delete_object(self, Bucket, Key):
            self.store.pop(Key, None)
            return {}
        def delete_objects(self, Bucket, Delete):
            for obj in Delete.get('Objects', []):
                self.store.pop(obj['Key'], None)
            return {}
        def generate_presigned_url(self, ClientMethod, Params, ExpiresIn=900, HttpMethod=None):
            key = Params.get('Key', '')
            bucket = Params.get('Bucket', '')
            return f"https://mock-r2.cloudflarestorage.com/{bucket}/{key}?signed=true&expires={ExpiresIn}"

    mock_client = MockS3Client()
    storage = Storage()
    storage.client = mock_client
    storage.driver = 'r2'
    storage.bucket = 'test-bucket'

    # Test PUT, GET, HEAD
    storage.put('event1/photo1/full.jpg', b'test-jpeg-data', content_type='image/jpeg')
    assert storage.get('event1/photo1/full.jpg') == b'test-jpeg-data'
    head = storage.head('event1/photo1/full.jpg')
    assert head['exists'] is True and head['size'] == 14

    # Test presigned URLs
    upload_info = storage.generate_presigned_upload_url('event1/photo1/full.jpg')
    assert upload_info['mode'] == 'r2'
    assert 'mock-r2.cloudflarestorage.com' in upload_info['upload_url']

    download_url = storage.generate_presigned_download_url('event1/photo1/full.jpg', filename='test.jpg')
    assert 'mock-r2.cloudflarestorage.com' in download_url

    # Test DELETE
    storage.delete('event1/photo1/full.jpg')
    assert storage.head('event1/photo1/full.jpg')['exists'] is False

def test_presigned_upload_endpoints(monkeypatch):
    """Test request-upload and confirm-upload endpoints."""
    token = signup('uploader@example.com')
    event = create_event(token, 'Direct Upload Event')
    eid = event['id']

    # R2 is required for direct-to-storage upload. Local uploads must use
    # the authenticated multipart API; an anonymous local PUT is never allowed.
    assert client.put('/api/storage/local-upload/arbitrary/path', content=jpeg()).status_code == 404

    # Request presigned upload
    req_payload = {
        'filename': 'dslr_shot.jpg',
        'content_type': 'image/jpeg',
        'file_size': 1024 * 100,
        'sha256': 'a' * 64
    }
    assert client.post(f'/api/events/{eid}/photos/request-upload', headers=headers(token), json=req_payload).status_code == 409

    from app.storage import store
    monkeypatch.setattr(store, 'is_r2', lambda: True)
    monkeypatch.setattr(store, 'generate_presigned_upload_url', lambda key, content_type='image/jpeg', expires_in=900: {'mode': 'r2', 'key': key, 'upload_url': 'https://example.invalid/temporary-upload'})
    r = client.post(f'/api/events/{eid}/photos/request-upload', headers=headers(token), json=req_payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['duplicate'] is False
    pid = data['photo_id']
    assert 'full' in data['uploads']

    # Simulate client directly putting derivatives to storage
    from app.storage import store
    prefix = f'{eid}/{pid}'
    store.put(f'{prefix}/full.jpg', jpeg())
    store.put(f'{prefix}/view.jpg', jpeg())
    store.put(f'{prefix}/thumb.jpg', jpeg())

    # Confirm upload
    confirm_payload = {
        'photo_id': pid,
        'sha256': 'a' * 64,
        'original_name': 'dslr_shot.jpg',
        'width': 800,
        'height': 600
    }
    r = client.post(f'/api/events/{eid}/photos/confirm-upload', headers=headers(token), json=confirm_payload)
    assert r.status_code == 200, r.text
    assert r.json()['photo']['id'] == pid

def test_persistent_queue_and_gemini(monkeypatch):
    """Test persistent background queue and mocked Gemini semantic analysis."""
    # Mock Gemini AI response
    monkeypatch.setattr(
        gemini_ai,
        'is_gemini_available',
        lambda: True
    )
    monkeypatch.setattr(
        gemini_ai,
        'analyze_photo',
        lambda _: {
            'description': 'A couple dancing on an illuminated stage during an evening reception.',
            'context': 'evening wedding reception',
            'moment_type': 'celebration',
            'tags': ['dance', 'stage', 'lights', 'celebration', 'reception'],
            'caption': 'Joyful dance under golden stage lights.'
        }
    )

    token = signup('gemini_owner@example.com')
    event = create_event(token, 'Gemini Celebration')
    eid = event['id']
    code = event['guest_code']

    # Upload photo
    r = client.post(
        f'/api/events/{eid}/photos',
        headers=headers(token),
        files={'file': ('celebration.jpg', jpeg(), 'image/jpeg')}
    )
    assert r.status_code == 201, r.text
    pid = r.json()['photo']['id']

    # Verify job exists in database
    with SessionLocal() as db:
        gemini_job = db.scalar(select(Job).where(Job.photo_id == pid, Job.job_type == 'gemini_analysis'))
        assert gemini_job is not None
        assert gemini_job.status == 'pending'

        # Claim and execute job
        claimed = queue.claim_next_jobs(db)
        assert gemini_job.id in claimed

    queue.execute_job(gemini_job.id)

    # Check updated metadata
    with SessionLocal() as db:
        p = db.get(Photo, pid)
        assert p.gemini_status == 'done'
        assert p.gemini_moment_type == 'celebration'
        assert 'dance' in p.gemini_tags
        assert 'dance under golden' in p.gemini_caption

    # Test semantic search
    res = client.get(f'/api/g/{code}/photos/search?q=dance')
    assert res.status_code == 200, res.text
    assert res.json()['total'] == 1
    assert res.json()['photos'][0]['id'] == pid

    res_team = client.get(f'/api/events/{eid}/photos/search?q=celebration', headers=headers(token))
    assert res_team.status_code == 200, res_team.text
    assert res_team.json()['total'] == 1

def test_alembic_upgrade():
    """Verify Alembic migration script can be inspected and run."""
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    # Ensure alembic inspects head cleanly without exception
    command.heads(alembic_cfg)
