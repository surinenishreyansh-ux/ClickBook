"""Unit tests for photographer-side RAW development, no real camera or Cloudinary."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'clickbook_uploader.py'
spec = importlib.util.spec_from_file_location('clickbook_uploader', SCRIPT)
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


class RawFixture:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def postprocess(self, **kwargs):
        self.calls.append(kwargs)
        rgb = np.zeros((120, 180, 3), dtype=np.uint8)
        rgb[:, :, 0] = 120
        rgb[:, :, 1] = 80
        rgb[:, :, 2] = 70
        return rgb


class RawUploaderTests(unittest.TestCase):
    def make_rawpy(self, raw):
        fake = types.ModuleType('rawpy')
        fake.imread = lambda path: raw
        fake.ColorSpace = types.SimpleNamespace(sRGB=object())
        return fake

    def test_raw_develops_to_real_jpeg_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp, 'IMG_1001.NEF')
            raw_path.write_bytes(b'synthetic RAW input - do not upload')
            original_bytes = raw_path.read_bytes()
            fake_raw = RawFixture()
            with mock.patch.dict(sys.modules, {'rawpy': self.make_rawpy(fake_raw)}):
                result = uploader.prepare_photo(raw_path)
            blob, name, mime, size = result
            self.assertEqual(name, 'IMG_1001.jpg')
            self.assertEqual(mime, 'image/jpeg')
            self.assertEqual(raw_path.read_bytes(), original_bytes)
            self.assertTrue(blob.startswith(b'\xff\xd8'))
            with Image.open(io.BytesIO(blob)) as decoded:
                self.assertEqual(decoded.size, (180, 120))
                self.assertEqual(decoded.format, 'JPEG')
                self.assertNotIn('exif', decoded.info)
            self.assertEqual(size, (180, 120))
            self.assertTrue(fake_raw.calls[0]['use_camera_wb'])
            self.assertEqual(fake_raw.calls[0]['output_bps'], 8)

    def test_raw_dependency_message_if_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'IMG_1002.CR3')
            path.write_bytes(b'synthetic')
            with mock.patch.dict(sys.modules, {'rawpy': None}):
                with self.assertRaisesRegex(RuntimeError, 'requirements-raw.txt'):
                    uploader.develop_raw(path)

    def test_upload_sends_only_processed_jpeg_not_original_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp, 'DSC0001.ARW')
            raw_path.write_bytes(b'SECRET_RAW_CAMERA_FILE_CONTENT')
            raw = RawFixture()
            captured = []
            def urlopen(request, timeout):
                captured.append((request, timeout))
                return io.BytesIO(b'{"photo":{"id":"sample"},"duplicate":false}')
            with mock.patch.dict(sys.modules, {'rawpy': self.make_rawpy(raw)}):
                with mock.patch.object(uploader, 'urlopen', urlopen):
                    result = uploader.upload_file('https://example.test/api/events/abc/photos', 'short-lived-secret', raw_path)
            self.assertFalse(result['duplicate'])
            req = captured[0][0]
            self.assertIn(b'filename="DSC0001.jpg"', req.data)
            self.assertIn(b'Content-Type: image/jpeg', req.data)
            self.assertIn(b'\xff\xd8', req.data)
            self.assertNotIn(b'SECRET_RAW_CAMERA_FILE_CONTENT', req.data)
            self.assertEqual(raw_path.read_bytes(), b'SECRET_RAW_CAMERA_FILE_CONTENT')

    def test_raw_and_jpeg_pair_only_publishes_one_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            folder.joinpath('DSC_500.CR3').write_bytes(b'RAW_CAMERA_BYTES')
            jpeg_path = folder / 'DSC_500.JPG'
            Image.new('RGB', (100, 100)).save(jpeg_path)
            calls = []
            def fake_upload(url, token, path, **kwargs):
                calls.append((path.name, kwargs['prepared'][1]))
                return {'duplicate': False}
            args = ['dslr', '--api', 'https://clickbook.example', '--event', 'event123', '--folder', temp, '--once']
            with mock.patch.dict(os.environ, {'CLICKBOOK_TOKEN': 'test-token'}):
                with mock.patch.object(sys, 'argv', args):
                    with mock.patch.object(uploader, 'upload_file', fake_upload):
                        with mock.patch.object(uploader.time, 'sleep', return_value=None):
                            uploader.run()
                            uploader.run()
            self.assertEqual(calls, [('DSC_500.JPG', 'DSC_500.JPG')])
            saved = json.loads((folder / '.clickbook-upload-state.json').read_text())
            self.assertIn('DSC_500.JPG', saved['event123'])
            self.assertNotIn('DSC_500.CR3', saved['event123'])

    def test_raw_uploaded_first_then_matching_jpeg_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw_path = folder / 'IMG_0099.NEF'
            raw_path.write_bytes(b'RAW_CAMERA_BYTES')
            calls = []
            def fake_prepare(path, **kwargs):
                return b'\xff\xd8synthetic', path.stem + '.jpg', 'image/jpeg', (10, 10)
            def fake_upload(url, token, path, **kwargs):
                calls.append(path.name)
                return {'duplicate': False}
            args = ['dslr', '--api', 'https://clickbook.example', '--event', 'event99', '--folder', temp, '--once']
            with mock.patch.dict(os.environ, {'CLICKBOOK_TOKEN': 'test-token'}):
                with mock.patch.object(sys, 'argv', args):
                    with mock.patch.object(uploader, 'prepare_photo', fake_prepare):
                        with mock.patch.object(uploader, 'upload_file', fake_upload):
                            with mock.patch.object(uploader.time, 'sleep', return_value=None):
                                uploader.run()
                                Image.new('RGB', (120, 120)).save(folder / 'IMG_0099.JPG')
                                uploader.run()
            self.assertEqual(calls, ['IMG_0099.NEF'])


if __name__ == '__main__':
    unittest.main()
