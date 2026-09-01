"""
Off-volume mirror for backup_service's local snapshots.

Why this exists: backup_service.py's snapshots live in DB_PATH.parent /
"backups" — the SAME persistent volume as the live database (/data on HF
Spaces). That protects against the one specific corruption this app has hit
(a duplicate sqlite_master catalog row — see utils/db.py), but not against
losing the volume itself (storage-tier issue, quota exhaustion, Space
rebuild/recreation). This module pushes each local snapshot to a private
Hugging Face Hub dataset repo so a real off-volume copy exists.

Requires HF_TOKEN (a write-scoped HF access token — huggingface_hub's own
default token env var, so nothing extra to wire up) and BACKUP_HF_REPO_ID
(the target private dataset repo, e.g. "your-username/curivio-backups").
The repo itself needs no manual setup: create_repo(..., exist_ok=True) makes
it on first push.

Every function here is non-fatal-friendly for its caller: RuntimeError means
"not configured" (raised immediately, cheap, no network attempted), anything
else network-shaped is retried up to 3 times (upload_snapshot) or logged and
swallowed (prune_remote) — callers in backup_service.py decide what "not
configured" or "still failed after retrying" means for them.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

import huggingface_hub
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError
from huggingface_hub.hf_api import RepoFile
from requests.exceptions import RequestException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

REPO_TYPE = "dataset"


@lru_cache(maxsize=1)
def _client() -> huggingface_hub.HfApi:
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN environment variable is not set")
    return huggingface_hub.HfApi(token=token)


def _repo_id() -> str:
    repo_id = os.getenv("BACKUP_HF_REPO_ID")
    if not repo_id:
        raise RuntimeError("BACKUP_HF_REPO_ID environment variable is not set")
    return repo_id


_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(RequestException),  # transient network only
    reraise=True,
)


@_retry
def upload_snapshot(path: Path) -> None:
    api = _client()
    repo_id = _repo_id()
    api.create_repo(repo_id, repo_type=REPO_TYPE, private=True, exist_ok=True)
    api.upload_file(
        path_or_fileobj=str(path), path_in_repo=path.name,
        repo_id=repo_id, repo_type=REPO_TYPE,
    )


def list_remote() -> list[dict]:
    """[{"filename": ..., "size_bytes": ...}] for every snapshot in the
    remote repo, or [] if the repo doesn't exist yet (nothing pushed yet).
    Filtered to .db files only — HF auto-adds a .gitattributes on first
    commit that isn't one of ours."""
    try:
        entries = _client().list_repo_tree(_repo_id(), repo_type=REPO_TYPE)
        return [
            {"filename": e.path, "size_bytes": e.size}
            for e in entries
            if isinstance(e, RepoFile) and e.path.endswith(".db")
        ]
    except RepositoryNotFoundError:
        return []


def download_to(filename: str, dest_dir: Path) -> Path:
    """Download one remote snapshot into dest_dir (which must already
    exist), returning the path to the downloaded file."""
    _client()  # validate HF_TOKEN before attempting the request
    try:
        downloaded = huggingface_hub.hf_hub_download(
            _repo_id(), filename, repo_type=REPO_TYPE, local_dir=str(dest_dir),
        )
    except EntryNotFoundError:
        raise FileNotFoundError(filename) from None
    return Path(downloaded)


def prune_remote(keep: int) -> list[str]:
    """Delete the oldest remote snapshots beyond `keep`, sorted by filename
    (chronological by construction, same reasoning as backup_service._prune).
    Never raises — pruning is best-effort cleanup, not something that should
    ever break the push that just succeeded."""
    try:
        names = sorted(r["filename"] for r in list_remote())
    except Exception:
        logger.warning("[backup] could not list remote snapshots for pruning", exc_info=True)
        return []
    removed = []
    for old in (names[:-keep] if len(names) > keep else []):
        try:
            _client().delete_file(old, repo_id=_repo_id(), repo_type=REPO_TYPE)
            removed.append(old)
        except Exception:
            logger.warning("[backup] could not prune remote %s", old, exc_info=True)
    return removed
