#!/usr/bin/env python3
"""ClickBook DSLR folder watcher with optional on-device RAW development.

The photographer's original RAW never leaves this computer. A high-quality,
sRGB JPEG is generated in memory and sent to the authenticated ClickBook
image API. Render/Cloudinary only receive the processed JPEG.

For RAW files: python -m pip install -r uploader/requirements-raw.txt
"""
import argparse
import getpass
import io
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

STANDARD_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
RAW_EXTS = {
    '.cr2', '.cr3', '.nef', '.nrw', '.arw', '.sr2',
    '.dng', '.raf', '.orf', '.rw2', '.pef', '.srw'
}
EXTS = STANDARD_EXTS | RAW_EXTS
JPEG_EXTS = {'.jpg', '.jpeg'}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def request_json(url, body, headers=None):
    data = json.dumps(body).encode('utf-8')
    req = Request(url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with urlopen(req, timeout=30) as res:
            return json.load(res)
    except HTTPError as exc:
        try:
            detail = json.load(exc).get('detail', exc.reason)
        except Exception:
            detail = exc.reason
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc


def develop_raw(path, max_side=4000, quality=88, half_size=False):
    """Develop DSLR RAW locally into a color-corrected, high-resolution JPEG.

    No RAW input, EXIF, or intermediate data is uploaded or written to disk.
    The normal backend still creates protected gallery/view/thumb variants.
    """
    try:
        import rawpy
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            'RAW support is not installed. Run: python -m pip install '
            '-r uploader/requirements-raw.txt (on the photographer computer).'
        ) from exc

    if not 1000 <= max_side <= 6000:
        raise ValueError('RAW max side must be between 1000 and 6000 pixels')
    if not 50 <= quality <= 95:
        raise ValueError('RAW JPEG quality must be between 50 and 95')

    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8,
                no_auto_bright=False,
                half_size=half_size
            )
        image = Image.fromarray(rgb)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        # Most RAW developments at 4000px easily fit under 25 MiB, but
        # recompress/reduce huge noisy pictures rather than uploading RAW.
        for side in (max_side, 3200, 2600, 2000):
            image.thumbnail((side, side), Image.Resampling.LANCZOS)
            for q in dict.fromkeys((quality, 85, 78, 70, 60)):
                buf = io.BytesIO()
                image.save(buf, 'JPEG', quality=min(q, quality), optimize=True, progressive=True)
                payload = buf.getvalue()
                if len(payload) <= MAX_UPLOAD_BYTES:
                    return payload, image.size
        raise RuntimeError('Converted JPEG still exceeds the 25 MB upload limit')
    except Exception as exc:
        if isinstance(exc, (RuntimeError, ValueError)):
            raise
        raise RuntimeError(
            'RAW development failed. This camera/RAW encoding may not be '
            'supported by your installed LibRaw version.'
        ) from exc


def prepare_photo(path, max_side=4000, quality=88, half_size=False):
    """Return bytes, upload filename, content-type, and whether RAW was developed."""
    if path.suffix.lower() in RAW_EXTS:
        data, size = develop_raw(path, max_side=max_side, quality=quality, half_size=half_size)
        return data, path.stem + '.jpg', 'image/jpeg', size

    data = path.read_bytes()
    if len(data) > MAX_UPLOAD_BYTES:
        raise RuntimeError('File larger than 25 MB upload limit')
    return data, path.name, mimetypes.guess_type(path.name)[0] or 'image/jpeg', None


def upload_file(url, token, path, *, prepared=None, raw_max_side=4000, raw_quality=88, raw_half_size=False):
    if prepared is None:
        prepared = prepare_photo(path, max_side=raw_max_side, quality=raw_quality, half_size=raw_half_size)
    data, name, mime, dimensions = prepared
    if len(data) > MAX_UPLOAD_BYTES:
        raise RuntimeError('Image exceeds the 25 MB upload limit')
    # Avoid filenames breaking multipart form headers.
    safe_name = name.replace('"', '_').replace('\r', '_').replace('\n', '_')
    boundary = '----clickbook' + uuid.uuid4().hex
    pre = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f'Content-Type: {mime}\r\n\r\n'
    ).encode()
    post = f'\r\n--{boundary}--\r\n'.encode()
    req = Request(
        url,
        data=pre + data + post,
        headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Authorization': f'Bearer {token}'
        },
        method='POST'
    )
    try:
        with urlopen(req, timeout=120) as res:
            return json.load(res)
    except HTTPError as exc:
        try:
            detail = json.load(exc).get('detail', exc.reason)
        except Exception:
            detail = exc.reason
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc


def run():
    parser = argparse.ArgumentParser(
        description='Auto-develop DSLR RAW/JPEG files and publish JPEGs to ClickBook'
    )
    parser.add_argument('--api', default=os.environ.get('CLICKBOOK_API_URL', 'http://127.0.0.1:8000'),
                        help='ClickBook public URL or local backend URL')
    parser.add_argument('--event', required=True, help='Event ID from ClickBook organizer dashboard')
    parser.add_argument('--folder', required=True, help='Folder your tethering software saves camera images to')
    parser.add_argument('--email', default=os.environ.get('CLICKBOOK_EMAIL', ''),
                        help='Approved photographer login email (password prompted securely)')
    parser.add_argument('--once', action='store_true', help='Upload stable existing photos once, then exit')
    parser.add_argument('--interval', type=float, default=3, help='Scan interval (seconds)')
    parser.add_argument('--raw-max-side', type=int, default=4000, help='Longest edge of RAW JPEG (default 4000)')
    parser.add_argument('--raw-quality', type=int, default=88, help='RAW JPEG quality 50..95 (default 88)')
    parser.add_argument('--raw-half-size', action='store_true',
                        help='Reduce RAW decoding RAM/CPU for low-memory photographer laptops')
    args = parser.parse_args()
    if not 1000 <= args.raw_max_side <= 6000:
        parser.error('--raw-max-side must be 1000..6000')
    if not 50 <= args.raw_quality <= 95:
        parser.error('--raw-quality must be 50..95')
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        parser.error(f'Folder does not exist: {folder}')
    root = args.api.rstrip('/')
    if not (root.startswith('https://') or root.startswith('http://localhost') or
            root.startswith('http://127.0.0.1')):
        parser.error('Use an HTTPS ClickBook URL (HTTP allowed only on localhost)')
    token = os.environ.get('CLICKBOOK_TOKEN', '')
    if not token:
        if not args.email:
            parser.error('Specify --email or CLICKBOOK_TOKEN environment variable')
        password = getpass.getpass('ClickBook password: ')
        token = request_json(root + '/api/auth/login', {'email': args.email, 'password': password})['token']

    print('Watching:', folder)
    print('Event ID:', args.event)
    print('RAW input supported (depends on camera model/LibRaw):', ', '.join(sorted(RAW_EXTS)))
    print('RAW originals remain on this computer; only processed JPEGs are uploaded.')
    state_path = folder / '.clickbook-upload-state.json'
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    done = state.get(args.event, {})
    if not isinstance(done, dict):
        done = {}
    observed = {}
    recent_errors = {}

    def scan():
        paths = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in EXTS]
        # When cameras save RAW+JPEG pairs, upload only the camera JPEG.
        # If RAW was already uploaded before its JPEG arrived, skip the pair.
        available_jpg_stems = {p.stem.casefold() for p in paths if p.suffix.lower() in JPEG_EXTS}
        uploaded_stems = {Path(name).stem.casefold(): name for name in done}
        paths.sort(key=lambda p: (p.stem.casefold(), p.suffix.lower() not in JPEG_EXTS, p.name))

        for path in paths:
            stem = path.stem.casefold()
            if path.suffix.lower() in RAW_EXTS and stem in available_jpg_stems:
                continue
            if stem in uploaded_stems and uploaded_stems[stem] != path.name:
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            signature = f'{info.st_size}:{info.st_mtime_ns}'
            if done.get(path.name) == signature or info.st_size == 0:
                continue
            if observed.get(path.name) != signature:
                observed[path.name] = signature
                continue  # wait another scan to confirm tethering finished writing

            try:
                prepared = prepare_photo(
                    path, max_side=args.raw_max_side, quality=args.raw_quality,
                    half_size=args.raw_half_size
                )
                result = upload_file(root + f'/api/events/{args.event}/photos', token, path,
                                     prepared=prepared)
                done[path.name] = signature
                uploaded_stems[stem] = path.name
                state[args.event] = done
                tmp = state_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(state, indent=2))
                tmp.replace(state_path)
                label = 'already present' if result.get('duplicate') else 'uploaded live'
                kind = ' (RAW developed to JPEG)' if path.suffix.lower() in RAW_EXTS else ''
                print(f'[{time.strftime("%H:%M:%S")}] {label}: {path.name}{kind}', flush=True)
                recent_errors.pop(path.name, None)
            except Exception as exc:
                # Don't fill logs with the same error every few seconds.
                reason = str(exc)
                if recent_errors.get(path.name) != reason:
                    print(f'[{time.strftime("%H:%M:%S")}] failed: {path.name}: {reason}',
                          file=sys.stderr, flush=True)
                    recent_errors[path.name] = reason

    try:
        while True:
            scan()
            if args.once:
                time.sleep(1)
                scan()
                break
            time.sleep(max(1, args.interval))
    except KeyboardInterrupt:
        print('\nUploader stopped. Unmodified RAW originals remain in:', folder)


if __name__ == '__main__':
    run()
