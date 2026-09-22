"""The S3 adapter transfers bytes through an actual HTTP object-store API."""

from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto.server import ThreadedMotoServer

from app.core.config import Settings
from app.documents import storage as storage_module
from app.documents.storage import DocumentStorageUnavailable, ObjectStorage


@pytest.fixture
def s3_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="isolated-test",
        aws_secret_access_key="isolated-test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket="documents-test")
    try:
        yield endpoint
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_real_s3_put_get_delete(s3_endpoint: str) -> None:
    storage = ObjectStorage(
        endpoint=s3_endpoint,
        bucket="documents-test",
        access_key="isolated-test",
        secret_key="isolated-test",
    )
    await storage.put("tenant/one", b"%PDF-1.7", "application/pdf")
    assert await storage.get("tenant/one") == b"%PDF-1.7"
    await storage.delete("tenant/one")
    with pytest.raises(DocumentStorageUnavailable):
        await storage.get("tenant/one")


def test_http_storage_endpoint_is_loopback_and_nonproduction_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_module.get_object_storage.cache_clear()
    for environment, endpoint in (
        ("production", "http://127.0.0.1:9001"),
        ("development", "http://object-store.example:9001"),
        ("development", "http://user:pass@127.0.0.1:9001"),
    ):
        settings = Settings(
            _env_file=None,
            app_env=environment,
            object_storage_endpoint_url=endpoint,
            object_storage_bucket="documents-test",
            object_storage_access_key="isolated-test",
            object_storage_secret_key="isolated-test",
        )
        monkeypatch.setattr(storage_module, "get_settings", lambda settings=settings: settings)
        with pytest.raises(DocumentStorageUnavailable):
            storage_module.get_object_storage()
    storage_module.get_object_storage.cache_clear()
