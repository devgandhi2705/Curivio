"""
Gemini embedding helper — LangChain foundation, Step 3.

Additive-only, parallel to the existing hand-rolled call sites. Plumbing for
later vector-search phases; no application vector schema lives here.

Public API
----------
get_embedding_model() -> GoogleGenerativeAIEmbeddings
get_embedding(text)   -> list[float]
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from ..config import GEMINI_EMBEDDING_MODEL


def _gemini_key() -> str:
    raw = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS environment variable is not set")
    return keys[0]


def get_embedding_model() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL, google_api_key=_gemini_key())


def get_embedding(text: str) -> list[float]:
    return get_embedding_model().embed_query(text)
