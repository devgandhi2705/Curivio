"""
Dictionary fast-path — dictionaryapi.dev lookups for single common English
words, skipping the LLM entirely (see unpack-feature-spec.md).

Public API
----------
is_dictionary_fast_path_eligible(term) -> bool
dictionary_lookup(word)                -> dict | None
"""

import logging
import re

import requests

logger = logging.getLogger(__name__)

_DICTIONARY_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"
_SINGLE_WORD_RE      = re.compile(r"^[A-Za-z']+$")


def is_dictionary_fast_path_eligible(term: str) -> bool:
    """Single common English word."""
    return bool(_SINGLE_WORD_RE.match(term.strip()))


def dictionary_lookup(word: str) -> dict | None:
    """
    Look up a single word via dictionaryapi.dev.
    Returns a partial Unpack result dict, or None on any failure/miss.
    """
    word = word.strip()
    if not word:
        return None
    try:
        resp = requests.get(_DICTIONARY_API_URL.format(word.lower()), timeout=4)
        if resp.status_code != 200:
            return None
        entry      = resp.json()[0]
        meaning    = entry["meanings"][0]
        definition = meaning["definitions"][0]["definition"]
        return {
            "term":                word,
            "definition_general":  definition,
            "meaning_in_context":  None,
            "confidence":          "high",
        }
    except Exception as exc:
        logger.debug("[dictionary] lookup failed for %r: %s", word, exc)
        return None
