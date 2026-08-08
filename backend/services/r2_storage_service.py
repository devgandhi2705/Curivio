"""
Chat-R13 — thin S3-compatible wrapper around Cloudflare R2 for chat document
attachment original-bytes retention.

Scope: original uploaded bytes only, for document attachments (pdf/docx/csv/
text/code, doc://<attachment_id> uris) — never the extracted text/embeddings
in document_chunks_vec (document_memory_service.py), which are permanent and
untouched by this module. Never used for image attachments (those stay on
Gemini's Files API, per model_provider.upload_attachment).

R12 confirmed: real upload/download/delete work against this credential;
GetBucketLifecycleConfiguration returns AccessDenied (object-scoped token,
no admin/lifecycle permission) — so retention here is enforced app-side by
sweep_expired_attachments() (chat_service.py), never an R2 lifecycle rule.

Public API
----------
upload(data: bytes, key: str, content_type: str | None = None) -> None
download(key: str) -> bytes
download_stream(key: str) -> tuple[Iterator[bytes], int | None]
    Chat-R14a — real streaming (StreamingBody.iter_chunks), never full-buffer;
    for the binary-serving endpoint, given attachments up to 50MB. Returns
    (chunk iterator, Content-Length or None if R2 didn't report one).
delete(key: str) -> None
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Iterator

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client():
    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        raise RuntimeError(
            "R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY environment variable is not set"
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _bucket() -> str:
    bucket = os.getenv("R2_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("R2_BUCKET_NAME environment variable is not set")
    return bucket


def upload(data: bytes, key: str, content_type: str | None = None) -> None:
    try:
        _client().put_object(
            Bucket=_bucket(), Key=key, Body=data,
            ContentType=content_type or "application/octet-stream",
        )
    except ClientError as exc:
        logger.error("[r2] upload failed for key=%r: %s", key, exc)
        raise


def download(key: str) -> bytes:
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=key)
        return resp["Body"].read()
    except ClientError as exc:
        logger.error("[r2] download failed for key=%r: %s", key, exc)
        raise


_STREAM_CHUNK_SIZE = 64 * 1024


def download_stream(key: str) -> tuple[Iterator[bytes], int | None]:
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        logger.error("[r2] download_stream failed for key=%r: %s", key, exc)
        raise
    body = resp["Body"]
    content_length = resp.get("ContentLength")

    def _chunks() -> Iterator[bytes]:
        for chunk in body.iter_chunks(chunk_size=_STREAM_CHUNK_SIZE):
            yield chunk

    return _chunks(), content_length


def delete(key: str) -> None:
    try:
        _client().delete_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        logger.error("[r2] delete failed for key=%r: %s", key, exc)
        raise
