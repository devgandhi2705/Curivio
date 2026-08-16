"""
Feed v2 link ingestion — main-content extraction via the TinyFish Fetch API,
called DIRECTLY (the chat path's tinyfish_service sits behind the isolation
boundary). TinyFish renders JS and returns clean markdown with nav/ads/
boilerplate stripped server-side, so no local HTML extractor is needed.

The EXTRACTED TEXT becomes the material's retrievable content; the original URL
is kept only as metadata (v2_materials.url), never as the retrievable content.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[4] / ".env")

logger = logging.getLogger(__name__)

_FETCH_URL = "https://api.fetch.tinyfish.ai"
_FETCH_TIMEOUT_S = 60  # TinyFish renders real JS pages — needs headroom
_MOCK = os.getenv("MOCK_RETRIEVAL", "").lower() == "true"


@dataclass
class LinkResult:
    text: str | None = None
    title: str = ""
    error: str | None = None


def fetch_link(url: str) -> LinkResult:
    """Fetch one URL's main content as markdown. Returns text OR error, never both."""
    if _MOCK:
        return LinkResult(text=f"Mock fetched content for {url}", title="Mock Page")

    api_key = os.getenv("TINYFISH_API_KEY", "")
    if not api_key:
        return LinkResult(error="TINYFISH_API_KEY not set")

    try:
        resp = requests.post(
            _FETCH_URL,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={"urls": [url], "format": "markdown", "image_links": False, "ttl": 0},
            timeout=_FETCH_TIMEOUT_S,
        )
        resp.raise_for_status()
    except Exception as exc:
        return LinkResult(error=f"TinyFish fetch failed: {exc}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        errs = data.get("errors", [])
        detail = errs[0].get("error") if errs else "no content returned"
        return LinkResult(error=f"TinyFish returned no content for {url}: {detail}")

    r = results[0]
    text = (r.get("text") or "").strip()
    if not text:
        return LinkResult(error=f"TinyFish returned empty content for {url}")
    return LinkResult(text=text, title=r.get("title") or "")
