"""
Safety net: the five stale default schemas are never what a real call sends.

AGENT_SCHEMAS still holds Phase 3 placeholders for lesson_planner, web_researcher,
source_ranker, section_writer and visual_director: a bare {"type": "array"} with no
`items`. call_agent sends that default when a call site omits schema=, and Gemini 400s
on it ("response_schema.properties[...].items: missing field"). The call then silently
lands on the free fallback (seen for real on 2026-09-19 with lesson_planner). Today every
call site passes its own schema; this test makes a call site that stops doing so fail
here instead of shipping a 400. It does not fix the placeholders.
"""
import ast
import glob
import importlib

import pytest

from backend.services.feed_v2.llm.provider import AGENT_SCHEMAS

STALE = ("lesson_planner", "web_researcher", "source_ranker", "section_writer", "visual_director")


def _has_bare_array(schema) -> bool:
    if isinstance(schema, dict):
        if schema.get("type") == "array" and "items" not in schema:
            return True
        return any(_has_bare_array(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_has_bare_array(v) for v in schema)
    return False


def _violations(source: str, module=None) -> list[str]:
    """Every call_agent(<stale agent>, ...) must pass schema=<something other than None>;
    a schema that is a module-level name must itself be Gemini-valid (no bare arrays)."""
    out = []
    for n in ast.walk(ast.parse(source)):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "call_agent"):
            continue
        if not n.args or not isinstance(n.args[0], ast.Constant):
            out.append(f"line {n.lineno}: agent is not a literal, can't verify its schema")
            continue
        agent = n.args[0].value
        if agent not in STALE:
            continue
        kw = next((k for k in n.keywords if k.arg == "schema"), None)
        if kw is None or (isinstance(kw.value, ast.Constant) and kw.value.value is None):
            out.append(f"line {n.lineno}: {agent} call sends the stale AGENT_SCHEMAS default")
        elif isinstance(kw.value, ast.Name) and module is not None and hasattr(module, kw.value.id):
            if _has_bare_array(getattr(module, kw.value.id)):
                out.append(f"line {n.lineno}: {agent} schema {kw.value.id} has a bare array")
    return out


def _call_sites():
    for path in sorted(glob.glob("backend/services/feed_v2/**/*.py", recursive=True)):
        src = open(path, encoding="utf-8").read()
        if "call_agent(" in src:
            mod = path.removesuffix(".py").replace("\\", "/").replace("/", ".")
            yield path, src, importlib.import_module(mod)


def test_the_five_defaults_really_are_stale():
    """Why this guard exists. If a placeholder gets fixed, drop it from STALE."""
    assert all(_has_bare_array(AGENT_SCHEMAS[a]) for a in STALE)


def test_every_call_site_for_a_stale_agent_passes_its_own_schema():
    found, problems = set(), []
    for path, src, mod in _call_sites():
        problems += [f"{path} {v}" for v in _violations(src, mod)]
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "call_agent" \
                    and n.args and isinstance(n.args[0], ast.Constant):
                found.add(n.args[0].value)
    assert problems == []
    assert set(STALE) <= found, f"no call site found for {set(STALE) - found}: the scan would pass vacuously"


@pytest.mark.parametrize("snippet", [
    "call_agent('lesson_planner', msgs, system=s, meta=m)",
    "call_agent('section_writer', msgs, schema=None)",
])
def test_the_guard_catches_a_missing_override(snippet):
    assert _violations(snippet)
