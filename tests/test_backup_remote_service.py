"""
Tests for backend.services.backup_remote_service — thin wrapper pushing
backup_service's local snapshots to a private HF Hub dataset repo. Mocks
huggingface_hub so these run without real network calls; a real end-to-end
smoke test (create_repo/upload_file/list_repo_tree/hf_hub_download/delete_file
against Devg-01/curivio-backups) was run manually against huggingface_hub
1.29.0 before writing this — see the naming/signatures this file assumes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import backup_remote_service as remote


@pytest.fixture(autouse=True)
def clear_client_cache():
    remote._client.cache_clear()
    yield
    remote._client.cache_clear()


@pytest.fixture
def env_creds(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    monkeypatch.setenv("BACKUP_HF_REPO_ID", "Devg-01/curivio-backups-test")


def _repo_file(path, size):
    f = MagicMock()
    f.__class__ = remote.RepoFile
    f.path = path
    f.size = size
    return f


class TestMissingConfig:
    def test_upload_raises_runtime_error_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="HF_TOKEN"):
            remote.upload_snapshot(Path("x.db"))

    def test_list_raises_runtime_error_when_repo_id_missing(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_test_token")
        monkeypatch.delenv("BACKUP_HF_REPO_ID", raising=False)
        with pytest.raises(RuntimeError, match="BACKUP_HF_REPO_ID"):
            remote.list_remote()


class TestUploadSnapshot:
    def test_creates_repo_then_uploads_with_original_filename(self, env_creds, tmp_path):
        snap = tmp_path / "curivio-20260901-000000-auto.db"
        snap.write_bytes(b"data")
        mock_api = MagicMock()
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            remote.upload_snapshot(snap)
        mock_api.create_repo.assert_called_once_with(
            "Devg-01/curivio-backups-test", repo_type="dataset", private=True, exist_ok=True,
        )
        mock_api.upload_file.assert_called_once_with(
            path_or_fileobj=str(snap), path_in_repo=snap.name,
            repo_id="Devg-01/curivio-backups-test", repo_type="dataset",
        )


class TestListRemote:
    def test_maps_repo_files_to_filename_and_size(self, env_creds):
        mock_api = MagicMock()
        mock_api.list_repo_tree.return_value = [
            _repo_file(".gitattributes", 2504),
            _repo_file("curivio-20260901-000000-auto.db", 12345),
        ]
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            result = remote.list_remote()
        assert result == [{"filename": "curivio-20260901-000000-auto.db", "size_bytes": 12345}]

    def test_returns_empty_list_when_repo_does_not_exist_yet(self, env_creds):
        fake_response = httpx.Response(404, request=httpx.Request("GET", "https://huggingface.co"))
        mock_api = MagicMock()
        mock_api.list_repo_tree.side_effect = RepositoryNotFoundError("no such repo", response=fake_response)
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            assert remote.list_remote() == []


class TestDownloadTo:
    def test_returns_path_to_downloaded_file(self, env_creds, tmp_path):
        with patch("huggingface_hub.hf_hub_download", return_value=str(tmp_path / "f.db")):
            result = remote.download_to("f.db", tmp_path)
        assert result == tmp_path / "f.db"

    def test_translates_entry_not_found_to_file_not_found(self, env_creds, tmp_path):
        with patch("huggingface_hub.hf_hub_download", side_effect=EntryNotFoundError("nope")):
            with pytest.raises(FileNotFoundError):
                remote.download_to("missing.db", tmp_path)


class TestPruneRemote:
    def test_deletes_oldest_beyond_keep_count(self, env_creds):
        mock_api = MagicMock()
        mock_api.list_repo_tree.return_value = [
            _repo_file(f"curivio-2026010{i}-000000-t.db", 100) for i in range(1, 6)
        ]
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            removed = remote.prune_remote(keep=3)
        assert removed == ["curivio-20260101-000000-t.db", "curivio-20260102-000000-t.db"]
        assert mock_api.delete_file.call_count == 2
        mock_api.delete_file.assert_any_call(
            "curivio-20260101-000000-t.db", repo_id="Devg-01/curivio-backups-test", repo_type="dataset",
        )

    def test_never_raises_when_listing_fails(self, env_creds):
        mock_api = MagicMock()
        mock_api.list_repo_tree.side_effect = RuntimeError("network down")
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            assert remote.prune_remote(keep=3) == []

    def test_nothing_to_prune_under_the_limit(self, env_creds):
        mock_api = MagicMock()
        mock_api.list_repo_tree.return_value = [_repo_file("curivio-20260101-000000-t.db", 100)]
        with patch("huggingface_hub.HfApi", return_value=mock_api):
            assert remote.prune_remote(keep=3) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
