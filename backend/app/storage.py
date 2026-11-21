import io
import logging
from pathlib import Path
from fastapi import HTTPException
from botocore.exceptions import ClientError
from .config import (
    DATA, STORAGE_DRIVER, STORAGE_BUCKET, STORAGE_ACCESS_KEY,
    STORAGE_SECRET_KEY, STORAGE_ENDPOINT, STORAGE_REGION, R2_PUBLIC_BASE_URL
)

log = logging.getLogger('clickbook.storage')

class Storage:
    def __init__(self):
        self.root = DATA / 'uploads'
        self.root.mkdir(parents=True, exist_ok=True)
        self.client = None
        self.driver = STORAGE_DRIVER
        self.bucket = STORAGE_BUCKET
        self.cloudinary = None

        if self.driver == 'cloudinary':
            from .cloudinary_storage import CloudinaryStorage
            self.cloudinary = CloudinaryStorage()
            log.info('Initialized Cloudinary authenticated private photo storage')
        elif self.driver == 'r2':
            import boto3
            from botocore.config import Config
            if not self.bucket:
                raise RuntimeError('R2_BUCKET_NAME must be configured when STORAGE_DRIVER is r2')
            if not STORAGE_ACCESS_KEY or not STORAGE_SECRET_KEY:
                raise RuntimeError('R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be configured')
            
            # S3 client configured for Cloudflare R2 compatibility
            self.client = boto3.client(
                's3',
                endpoint_url=STORAGE_ENDPOINT or None,
                aws_access_key_id=STORAGE_ACCESS_KEY,
                aws_secret_access_key=STORAGE_SECRET_KEY,
                region_name=STORAGE_REGION or 'auto',
                config=Config(
                    s3={'addressing_style': 'path'},
                    signature_version='s3v4',
                    retries={'max_attempts': 3, 'mode': 'standard'}
                )
            )
            log.info('Initialized Cloudflare R2 storage client (bucket: %s)', self.bucket)
        elif self.driver != 'local':
            raise RuntimeError(f'Unsupported STORAGE_DRIVER: {self.driver}. Must be local, r2 or cloudinary.')
        else:
            log.info('Using local disk storage adapter (path: %s)', self.root)

    def is_r2(self) -> bool:
        return self.client is not None and self.driver == 'r2'

    def put(self, key: str, data: bytes, content_type: str = 'image/jpeg'):
        """Store normalized image bytes in the configured storage backend."""
        if self.cloudinary:
            return self.cloudinary.put(key, data, content_type)
        if self.client:
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    CacheControl='private, max-age=3600'
                )
            except ClientError as e:
                log.exception('R2 put_object failed for key %s: %s', key, e)
                raise HTTPException(503, 'Cloud photo storage error during upload')
        else:
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def get(self, key: str) -> bytes:
        """Fetch private image bytes from the selected backend."""
        if self.cloudinary:
            return self.cloudinary.get(key)
        if self.client:
            try:
                resp = self.client.get_object(Bucket=self.bucket, Key=key)
                return resp['Body'].read()
            except ClientError as e:
                code = e.response.get('Error', {}).get('Code', '')
                if code in ('NoSuchKey', '404'):
                    raise HTTPException(404, 'Image not found in storage')
                log.exception('R2 get_object error for key %s: %s', key, e)
                raise HTTPException(503, 'Storage access error')
        p = self.root / key
        if not p.is_file():
            raise HTTPException(404, 'Image not found')
        return p.read_bytes()

    def head(self, key: str) -> dict:
        """Check whether an object exists."""
        if self.cloudinary:
            return self.cloudinary.head(key)
        if self.client:
            try:
                resp = self.client.head_object(Bucket=self.bucket, Key=key)
                return {
                    'exists': True,
                    'size': resp.get('ContentLength', 0),
                    'content_type': resp.get('ContentType', 'image/jpeg')
                }
            except ClientError as e:
                code = e.response.get('Error', {}).get('Code', '')
                if code in ('NoSuchKey', '404'):
                    return {'exists': False, 'size': 0, 'content_type': ''}
                log.exception('R2 head_object error for %s: %s', key, e)
                raise HTTPException(503, 'Storage verification error')
        p = self.root / key
        if p.is_file():
            return {'exists': True, 'size': p.stat().st_size, 'content_type': 'image/jpeg'}
        return {'exists': False, 'size': 0, 'content_type': ''}

    def delete(self, key: str):
        """Delete an object."""
        if self.cloudinary:
            return self.cloudinary.delete(key)
        if self.client:
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            except ClientError as e:
                log.warning('R2 delete_object error for key %s: %s', key, e)
        else:
            (self.root / key).unlink(missing_ok=True)

    def delete_many(self, keys: list[str]):
        """Bulk delete objects."""
        if not keys:
            return
        if self.cloudinary:
            return self.cloudinary.delete_many(keys)
        if self.client:
            try:
                objects = [{'Key': k} for k in keys]
                self.client.delete_objects(Bucket=self.bucket, Delete={'Objects': objects})
            except ClientError as e:
                log.warning('R2 delete_objects bulk deletion error: %s', e)
        else:
            for k in keys:
                (self.root / k).unlink(missing_ok=True)

    def generate_presigned_upload_url(self, key: str, content_type: str = 'image/jpeg', expires_in: int = 900) -> dict:
        """Generate a secure presigned PUT URL for direct browser-to-R2 upload."""
        if not self.client:
            raise HTTPException(409, 'Presigned uploads require R2. Use the authenticated multipart upload API.')
        try:
            url = self.client.generate_presigned_url(
                ClientMethod='put_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': key,
                    'ContentType': content_type
                },
                ExpiresIn=expires_in,
                HttpMethod='PUT'
            )
            return {
                'mode': 'r2',
                'key': key,
                'upload_url': url,
                'method': 'PUT',
                'headers': {'Content-Type': content_type},
                'expires_in': expires_in
            }
        except ClientError as e:
            log.exception('Failed to generate presigned upload URL: %s', e)
            raise HTTPException(500, 'Unable to generate upload authorization')

    def generate_presigned_download_url(self, key: str, expires_in: int = 900, filename: str | None = None) -> str:
        """Generate a secure time-limited presigned GET URL for private R2 object download."""
        if not self.client:
            # Local storage does not use external presigned URLs
            return ''
        params = {'Bucket': self.bucket, 'Key': key}
        if filename:
            params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
        else:
            params['ResponseContentDisposition'] = 'inline'
        try:
            return self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params=params,
                ExpiresIn=expires_in
            )
        except ClientError as e:
            log.warning('Failed to generate presigned download URL for %s: %s', key, e)
            return ''

store = Storage()
