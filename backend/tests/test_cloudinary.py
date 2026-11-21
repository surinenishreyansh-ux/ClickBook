"""Regression checks for Cloudinary's private-delivery adapter."""
import io
import sys
from types import ModuleType
import pytest
from fastapi import HTTPException
from app import cloudinary_storage as mod


def test_authenticated_cloudinary_storage(monkeypatch):
    sdk = ModuleType("cloudinary")
    sdk.__path__ = []
    api = ModuleType("cloudinary.api")
    uploader = ModuleType("cloudinary.uploader")
    utils = ModuleType("cloudinary.utils")
    sdk.api, sdk.uploader, sdk.utils = api, uploader, utils
    sdk.config = lambda **opts: None
    api.NotFound = type("NotFound", (Exception,), {})
    api.resource = lambda public_id, **opts: {"bytes": 100}

    calls = []
    def upload(payload, **opts):
        calls.append(opts)
        return {"type": opts["type"], "public_id": opts["public_id"]}
    uploader.upload = upload
    uploader.destroy = lambda public_id, **opts: {"result": "ok"}
    utils.private_download_url = lambda public_id, fmt, **opts: "https://api.cloudinary.com/v1_1/demo/image/download"
    for module in (sdk, api, uploader, utils):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"):
        monkeypatch.setattr(mod, name, "testing-only")

    class CloudResponse(io.BytesIO):
        def geturl(self):
            return "https://api.cloudinary.com/v1_1/demo/image/download"
    monkeypatch.setattr(mod, "urlopen", lambda url, timeout: CloudResponse(b"sample-jpeg"))

    storage = mod.CloudinaryStorage()
    key = "/".join(("a" * 32, "b" * 32, "full.jpg"))
    storage.put(key, b"sample-jpeg")
    assert calls[0]["type"] == "authenticated"
    assert calls[0]["overwrite"] is False
    assert storage.get(key) == b"sample-jpeg"
    assert storage.head(key)["exists"] is True
    storage.delete_many([key])
    with pytest.raises(ValueError):
        storage.public_id("../../arbitrary.jpg")

    uploader.destroy = lambda public_id, **opts: {"result": "error"}
    with pytest.raises(HTTPException) as error:
        storage.delete_many([key])
    assert error.value.status_code == 503
