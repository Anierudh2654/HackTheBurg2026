"""Content-addressed blob storage adapters."""
from __future__ import annotations

import hashlib
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse


class BlobConflict(RuntimeError):
    pass


class BlobStore:
    def __init__(self, url: str, s3_key: str = "", s3_secret: str = ""):
        parsed = urlparse(url)
        self.scheme = parsed.scheme
        self.s3 = None
        self.bucket = None
        if parsed.scheme == "file":
            path = (parsed.netloc + parsed.path) if parsed.netloc else parsed.path
            self.root = Path(path or ".").resolve()
            self.root.mkdir(parents=True, exist_ok=True)
        elif parsed.scheme == "s3":
            if not parsed.netloc:
                raise ValueError("s3:// blob URL requires a bucket")
            import boto3
            endpoint = parse_qs(parsed.query).get("endpoint", [None])[0]
            self.bucket = parsed.netloc
            self.s3 = boto3.client("s3", endpoint_url=endpoint,
                aws_access_key_id=s3_key or None, aws_secret_access_key=s3_secret or None)
            self.s3.head_bucket(Bucket=self.bucket)
            self.root = None
        else:
            raise ValueError("BLOB_URL must use file:// or s3://")

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._validate_key(key)
        if self.s3 is not None:
            try:
                existing = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self.s3.exceptions.NoSuchKey:
                existing = None
            except Exception as exc:
                if getattr(exc, "response", {}).get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                    raise
                existing = None
            if existing is not None:
                if existing != data:
                    raise BlobConflict(f"immutable blob differs for key {key}")
                return
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
            return
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise BlobConflict(f"immutable blob differs for key {key}")
            return
        target.write_bytes(data)

    def get(self, key: str) -> bytes:
        self._validate_key(key)
        if self.s3 is not None:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        self._validate_key(key)
        if self.s3 is not None:
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception as exc:
                if getattr(exc, "response", {}).get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise
        return self._path(key).is_file()

    def _path(self, key: str) -> Path:
        if self.root is None:
            raise RuntimeError("file path requested for S3 blob store")
        candidate = (self.root / key).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise ValueError("blob key escapes the configured store")
        return candidate

    @staticmethod
    def _validate_key(key: str) -> None:
        parts = PurePosixPath(key).parts
        if not key or key.startswith("/") or "\\" in key or ".." in parts:
            raise ValueError("invalid blob key")


def document_id(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()
