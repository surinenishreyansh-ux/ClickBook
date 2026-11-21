"""Cloudinary authenticated photo storage for ClickBook.

All uploads use Cloudinary's `authenticated` delivery type. Guest-facing
URLs are never Cloudinary URLs; the ClickBook API checks event access first
and streams authenticated assets through its own image endpoints.

Cloudinary `private` is intentionally NOT used, because its transformed
versions can otherwise be publicly accessible.
"""
import io
import logging
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from fastapi import HTTPException

from .config import (
    CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET,
    CLOUDINARY_FOLDER, MAX_IMAGE_MB, CLOUDINARY_MAX_ASSET_MB,
)

log = logging.getLogger('clickbook.cloudinary')

# The application generates its own 32-hex event and photo IDs. Restrict
# storage identifiers to those shapes; no client-supplied path is accepted.
_KEY_PATTERN = re.compile(r'^([a-f0-9]{32})/([a-f0-9]{32})/(full|view|thumb)\.jpg$')


class CloudinaryStorage:
    def __init__(self):
        if not all((CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)):
            raise RuntimeError('Cloudinary requires CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET')

        import cloudinary
        import cloudinary.api
        import cloudinary.uploader
        import cloudinary.utils

        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True,
        )
        self.api = cloudinary.api
        self.uploader = cloudinary.uploader
        self.utils = cloudinary.utils
        self.folder = CLOUDINARY_FOLDER

    def public_id(self, key: str) -> str:
        if not _KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid ClickBook photo storage key')
        return f'{self.folder}/{key[:-4]}'

    def put(self, key: str, data: bytes, content_type: str = 'image/jpeg') -> None:
        if content_type != 'image/jpeg':
            raise HTTPException(415, 'Cloudinary storage accepts normalized JPEG photos only')
        if len(data) > CLOUDINARY_MAX_ASSET_MB * 1024 * 1024:
            raise HTTPException(413, 'Image exceeds Cloudinary plan per-asset size limit')
        pid = self.public_id(key)
        try:
            result = self.uploader.upload(
                io.BytesIO(data),
                public_id=pid,
                type='authenticated',
                resource_type='image',
                format='jpg',
                overwrite=False,
                unique_filename=False,
            )
            if result.get('type') != 'authenticated' or result.get('public_id') != pid:
                log.error('Cloudinary upload returned unexpected asset metadata')
                raise RuntimeError('Unexpected Cloudinary upload result')
        except Exception as exc:
            log.warning('Cloudinary upload failed for storage key %s: %s', key, type(exc).__name__)
            raise HTTPException(503, 'Cloud photo storage unavailable during upload') from exc

    def get(self, key: str) -> bytes:
        pid = self.public_id(key)
        try:
            url = self.utils.private_download_url(
                pid, 'jpg', resource_type='image', type='authenticated',
                expires_at=int(time.time()) + 60,
            )
            parts = urlsplit(url)
            # Never fetch a user-provided hostname (or follow arbitrary redirects).
            if parts.scheme != 'https' or parts.hostname != 'api.cloudinary.com':
                raise ValueError('Unexpected Cloudinary download host')
            with urlopen(url, timeout=20) as response:
                if response.geturl().split('/')[2] != 'api.cloudinary.com':
                    raise ValueError('Unexpected Cloudinary redirect')
                content = response.read(MAX_IMAGE_MB * 1024 * 1024 + 1)
            if len(content) > MAX_IMAGE_MB * 1024 * 1024:
                raise HTTPException(413, 'Cloud image exceeds configured size limit')
            return content
        except HTTPException:
            raise
        except HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(404, 'Photo no longer exists') from exc
            log.warning('Cloudinary download returned HTTP %s', exc.code)
            raise HTTPException(503, 'Cloud photo temporarily unavailable') from exc
        except (URLError, OSError, ValueError) as exc:
            log.warning('Cloudinary download failed: %s', type(exc).__name__)
            raise HTTPException(503, 'Cloud photo temporarily unavailable') from exc

    def head(self, key: str) -> dict:
        pid = self.public_id(key)
        try:
            result = self.api.resource(pid, resource_type='image', type='authenticated')
            return {
                'exists': True,
                'size': result.get('bytes', 0),
                'content_type': 'image/jpeg',
            }
        except self.api.NotFound:
            return {'exists': False, 'size': 0, 'content_type': ''}
        except Exception as exc:
            log.warning('Cloudinary asset lookup failed: %s', type(exc).__name__)
            raise HTTPException(503, 'Cloud photo lookup unavailable') from exc

    def delete(self, key: str) -> None:
        self.delete_many([key])

    def delete_many(self, keys: list[str]) -> None:
        failed = []
        for key in keys:
            pid = self.public_id(key)
            try:
                result = self.uploader.destroy(
                    pid, resource_type='image', type='authenticated', invalidate=True,
                )
                if result.get('result') not in ('ok', 'not found'):
                    failed.append(key)
            except Exception as exc:
                log.warning('Cloudinary deletion failed for %s: %s', key, type(exc).__name__)
                failed.append(key)
        if failed:
            log.error('Failed to delete %d Cloudinary assets; database records retained for retry', len(failed))
            raise HTTPException(503, 'Cloud photo deletion incomplete. Please retry.')
