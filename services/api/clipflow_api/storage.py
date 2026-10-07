"""Object storage for rendered clips (PRD §B: S3-compatible, local adapter for development).

- `S3Storage`: MinIO locally, any S3 in staging/production. Preview links are presigned GETs
  that expire quickly (PRD §E `/clips/{id}/media`); the bucket stays private.
- `LocalStorage`: files under a directory; preview links point at the API's own signed
  `/v1/media/...` route. Used by tests and when no object storage is configured.

Neither the Agent nor the browser ever receives storage credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode


class Storage(Protocol):
    def put_file(self, key: str, path: Path, content_type: str) -> None: ...

    def preview_url(self, key: str, ttl_s: int) -> str: ...

    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: Path, api_base: str, signing_key: bytes):
        self.root, self.api_base, self._key = root, api_base.rstrip("/"), signing_key

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("key escapes the storage root")
        return path

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def sign(self, key: str, expires: int) -> str:
        return hmac.new(self._key, f"{key}|{expires}".encode(), hashlib.sha256).hexdigest()

    def preview_url(self, key: str, ttl_s: int) -> str:
        expires = int(time.time()) + ttl_s
        return f"{self.api_base}/v1/media/{key}?{urlencode({'exp': expires, 'sig': self.sign(key, expires)})}"

    def verify(self, key: str, expires: int, sig: str) -> Path | None:
        if expires < time.time() or not hmac.compare_digest(self.sign(key, expires), sig):
            return None
        path = self._path(key)
        return path if path.is_file() else None


class S3Storage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            region_name=region, config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        self._s3.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False

    def preview_url(self, key: str, ttl_s: int) -> str:
        return self._s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                                               ExpiresIn=ttl_s)
