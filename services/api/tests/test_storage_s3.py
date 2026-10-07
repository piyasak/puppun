"""S3Storage against the local compose MinIO (private bucket). Skipped when MinIO is not running."""

from __future__ import annotations

import socket
import uuid

import httpx
import pytest

from clipflow_api.storage import S3Storage

ENDPOINT = "http://127.0.0.1:9000"


def _minio_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9000), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _minio_up(), reason="MinIO not running (docker compose up -d minio minio-init)")


def test_put_presigned_preview_and_private_bucket(tmp_path):
    # Local development credentials from docker-compose.yml; never used outside this machine.
    storage = S3Storage(ENDPOINT, "clipflow-media", "clipflow", "clipflow_dev_secret")
    key = f"test/{uuid.uuid4().hex}/clip.mp4"
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake-mp4-bytes" * 100)
    storage.put_file(key, src, "video/mp4")
    assert storage.exists(key)

    url = storage.preview_url(key, ttl_s=60)
    resp = httpx.get(url)
    assert resp.status_code == 200 and resp.content == src.read_bytes()
    assert httpx.get(url, headers={"Range": "bytes=0-9"}).status_code == 206
    # Without the signature the private bucket refuses the same object.
    assert httpx.get(url.split("?", 1)[0]).status_code == 403
