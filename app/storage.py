from __future__ import annotations

import hashlib
import mimetypes
import re
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.client import Config

from .config import Settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class StorageConfigurationError(RuntimeError):
    pass


def storage_configuration_error(settings: Settings) -> str | None:
    if settings.storage_mode == "local":
        return None
    required = {
        "S3_ENDPOINT": settings.s3_endpoint,
        "S3_BUCKET": settings.s3_bucket,
        "S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return f"Missing object storage settings: {', '.join(missing)}"
    endpoint = str(settings.s3_endpoint or "").strip()
    lowered = endpoint.lower()
    if any(token in lowered for token in ("<cloudflare-account-id>", "<account_id>", "<account-id>", "your-account-id")) or "<" in endpoint or ">" in endpoint:
        return "S3_ENDPOINT still contains a placeholder. Configure the Cloudflare R2 S3 endpoint in Render."
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        return "S3_ENDPOINT must be a complete HTTPS URL."
    return None


def storage_configuration_status(settings: Settings) -> dict[str, str | bool | None]:
    error = storage_configuration_error(settings)
    return {
        "configured": error is None,
        "mode": settings.storage_mode,
        "endpoint": settings.s3_endpoint if error is None else None,
        "bucket": settings.s3_bucket if error is None else None,
        "error": error,
    }


def safe_filename(name: str) -> str:
    base = Path(name).name
    clean = _SAFE.sub("-", base).strip(".-")
    return clean[:180] or "upload.bin"


def build_storage_key(prospect_id: str, category: str, object_id: str, filename: str) -> str:
    return f"prospects/{prospect_id}/{category}/{object_id}/{safe_filename(filename)}"


@dataclass
class StoredObject:
    key: str
    size: int
    sha256: str
    mime_type: str


class ObjectStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.storage_mode == "local":
            settings.local_storage_root.mkdir(parents=True, exist_ok=True)
            self.client = None
        else:
            error = storage_configuration_error(settings)
            if error:
                raise StorageConfigurationError(error)
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                config=Config(signature_version="s3v4"),
            )

    def put_bytes(self, key: str, data: bytes, mime_type: str | None = None) -> StoredObject:
        content_type = mime_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        digest = hashlib.sha256(data).hexdigest()
        if self.settings.storage_mode == "local":
            path = self.settings.local_storage_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        else:
            assert self.client is not None and self.settings.s3_bucket
            self.client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
        return StoredObject(key=key, size=len(data), sha256=digest, mime_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        if self.settings.storage_mode == "local":
            return (self.settings.local_storage_root / key).read_bytes()
        assert self.client is not None and self.settings.s3_bucket
        return self.client.get_object(Bucket=self.settings.s3_bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        if self.settings.storage_mode == "local":
            path = self.settings.local_storage_root / key
            path.unlink(missing_ok=True)
            return
        assert self.client is not None and self.settings.s3_bucket
        self.client.delete_object(Bucket=self.settings.s3_bucket, Key=key)

    def signed_download_url(self, key: str, filename: str, mime_type: str) -> str | None:
        if self.settings.storage_mode == "local":
            return None
        assert self.client is not None and self.settings.s3_bucket
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe_filename(filename)}"',
                "ResponseContentType": mime_type,
            },
            ExpiresIn=self.settings.signed_url_ttl_seconds,
        )
