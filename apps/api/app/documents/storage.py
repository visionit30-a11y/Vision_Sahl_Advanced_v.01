"""Small S3-compatible object-storage boundary used by the document service."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError


class DocumentStorageUnavailable(AppError):
    code = "service_unavailable"
    status_code = 503
    message = "The service is temporarily unavailable."


class ObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=15,
                retries={"max_attempts": 2},
            ),
        )

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        try:
            await run_in_threadpool(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise DocumentStorageUnavailable() from exc

    async def get(self, key: str) -> bytes:
        try:
            response = await run_in_threadpool(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            body = response["Body"]
            try:
                return await run_in_threadpool(body.read, 10_485_761)
            finally:
                body.close()
        except (BotoCoreError, ClientError, OSError, KeyError) as exc:
            raise DocumentStorageUnavailable() from exc

    async def delete(self, key: str) -> None:
        try:
            await run_in_threadpool(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise DocumentStorageUnavailable() from exc


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    values = (
        settings.object_storage_endpoint_url,
        settings.object_storage_bucket,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
    )
    if not all(values):
        raise DocumentStorageUnavailable()
    endpoint, bucket, access_key, secret_key = values
    assert endpoint and bucket and access_key and secret_key
    parsed = urlparse(endpoint)
    loopback = parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and loopback and settings.app_env in {"development", "test"}
    ):
        raise DocumentStorageUnavailable()
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DocumentStorageUnavailable()
    return ObjectStorage(
        endpoint=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        region=settings.object_storage_region,
    )
