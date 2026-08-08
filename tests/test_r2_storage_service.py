"""
Tests for backend.services.r2_storage_service — Chat-R13's thin S3-compatible
wrapper around R2. Mocks boto3's client so these run without real network
calls; real-R2 verification is a separate live script (Chat-R13 STEP 3).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import r2_storage_service


@pytest.fixture(autouse=True)
def clear_client_cache():
    r2_storage_service._client.cache_clear()
    yield
    r2_storage_service._client.cache_clear()


@pytest.fixture
def env_creds(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key123")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret123")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")


def _client_error(op_name="PutObject", code="AccessDenied"):
    return ClientError({"Error": {"Code": code, "Message": "denied"}}, op_name)


class TestMissingCredentials:
    def test_upload_raises_runtime_error_when_creds_missing(self, monkeypatch):
        monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
        with pytest.raises(RuntimeError, match="R2_ACCOUNT_ID"):
            r2_storage_service.upload(b"data", "some/key")

    def test_download_raises_runtime_error_when_bucket_missing(self, monkeypatch, env_creds):
        monkeypatch.delenv("R2_BUCKET_NAME", raising=False)
        with pytest.raises(RuntimeError, match="R2_BUCKET_NAME"):
            r2_storage_service.download("some/key")


class TestUpload:
    def test_calls_put_object_with_bucket_key_body_content_type(self, env_creds):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            r2_storage_service.upload(b"hello", "chat-attachments/abc.txt", content_type="text/plain")
        mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket", Key="chat-attachments/abc.txt", Body=b"hello", ContentType="text/plain",
        )

    def test_defaults_content_type_when_none(self, env_creds):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            r2_storage_service.upload(b"hello", "k", content_type=None)
        assert mock_client.put_object.call_args.kwargs["ContentType"] == "application/octet-stream"

    def test_propagates_client_error_no_silent_failure(self, env_creds):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = _client_error()
        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(ClientError):
                r2_storage_service.upload(b"hello", "k")


class TestDownload:
    def test_returns_body_bytes(self, env_creds):
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"payload")}
        with patch("boto3.client", return_value=mock_client):
            result = r2_storage_service.download("chat-attachments/abc.txt")
        assert result == b"payload"
        mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="chat-attachments/abc.txt")

    def test_propagates_client_error_no_silent_failure(self, env_creds):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = _client_error("GetObject", "NoSuchKey")
        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(ClientError):
                r2_storage_service.download("missing-key")


class TestDownloadStream:
    def test_yields_chunks_and_content_length(self, env_creds):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.iter_chunks.return_value = iter([b"abc", b"def"])
        mock_client.get_object.return_value = {"Body": mock_body, "ContentLength": 6}
        with patch("boto3.client", return_value=mock_client):
            chunks, content_length = r2_storage_service.download_stream("chat-attachments/abc.pdf")
            collected = list(chunks)
        assert collected == [b"abc", b"def"]
        assert content_length == 6
        mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="chat-attachments/abc.pdf")

    def test_propagates_client_error_no_silent_failure(self, env_creds):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = _client_error("GetObject", "NoSuchKey")
        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(ClientError):
                r2_storage_service.download_stream("missing-key")


class TestDelete:
    def test_calls_delete_object(self, env_creds):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            r2_storage_service.delete("chat-attachments/abc.txt")
        mock_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="chat-attachments/abc.txt")

    def test_propagates_client_error_no_silent_failure(self, env_creds):
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = _client_error("DeleteObject", "AccessDenied")
        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(ClientError):
                r2_storage_service.delete("k")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
