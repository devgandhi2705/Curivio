"""
Isolation boundary for Feed v2 (Phase 1).

AST-walks every .py file under backend/services/feed_v2/ and resolves each
import. FAILS if any import resolves to a module under backend.services.*
(other than backend.services.feed_v2 itself) or under backend.llm.* — v2 must
not reach into legacy services or the legacy LLM layer.

Permitted external imports: stdlib, third-party packages already in
requirements, and read-only backend.database.* helpers (e.g. user_id lookups).
Only the two dangerous packages above are blocked.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FEED_V2_DIR = REPO_ROOT / "backend" / "services" / "feed_v2"

# feed_v2 itself is the one backend.services.* subtree that IS allowed.
_ALLOWED_SERVICES_PREFIX = "backend.services.feed_v2"


def _module_name(path: Path) -> str:
    """Dotted module name for a .py file relative to the repo root."""
    rel = path.resolve().relative_to(REPO_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-len(".py")]
    return ".".join(parts)


def _package_parts(path: Path) -> list[str]:
    """Package that a relative import in `path` is anchored to."""
    parts = _module_name(path).split(".")
    # A non-__init__ module's package is itself minus its last component;
    # an __init__.py module IS its own package.
    if path.name != "__init__.py":
        parts = parts[:-1]
    return parts


def _resolve_imports(path: Path, source: str):
    """Yield (lineno, dotted_module_name) for every import in `source`.

    Relative imports are resolved against `path`'s package so that e.g.
    `from ..chat_service import x` in a feed_v2 module resolves to
    backend.services.chat_service — the boundary we want to catch.
    """
    tree = ast.parse(source, filename=str(path))
    pkg = _package_parts(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name

        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                # Drop (level-1) trailing components off the anchor package.
                anchor = pkg[: len(pkg) - (node.level - 1)]
                base = ".".join(anchor)
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            if base:
                yield node.lineno, base
            # Each imported name may itself be a submodule (from pkg import sub).
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, f"{base}.{alias.name}" if base else alias.name


def _is_violation(name: str) -> bool:
    if name == "backend.llm" or name.startswith("backend.llm."):
        return True
    if name.startswith("backend.services."):
        if name == _ALLOWED_SERVICES_PREFIX or name.startswith(_ALLOWED_SERVICES_PREFIX + "."):
            return False
        return True
    return False


def find_violations() -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    for path in sorted(FEED_V2_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for lineno, name in _resolve_imports(path, source):
            if _is_violation(name):
                rel = path.relative_to(REPO_ROOT)
                violations.append((str(rel), lineno, name))
    return violations


def test_feed_v2_has_no_forbidden_imports():
    """The real boundary check: no feed_v2 file may import legacy services/llm."""
    assert FEED_V2_DIR.is_dir(), f"feed_v2 shell missing at {FEED_V2_DIR}"
    py_files = list(FEED_V2_DIR.rglob("*.py"))
    assert py_files, "no .py files found under feed_v2 — nothing was scanned"

    violations = find_violations()
    assert not violations, "Forbidden cross-boundary imports in feed_v2:\n" + "\n".join(
        f"  {f}:{ln} imports {name}" for f, ln, name in violations
    )


def test_checker_detects_forbidden_import(tmp_path):
    """Guard the checker itself: it must flag known-bad imports, not pass vacuously."""
    bad = (
        "import os\n"
        "from ..chat_service import chat_stream\n"   # backend.services.chat_service
        "from ...llm.model_provider import get_chat_model\n"  # backend.llm.model_provider
        "import backend.services.auth_service\n"
    )
    # Place a fake module at the feed_v2 depth so relative resolution matches prod.
    fake = FEED_V2_DIR / "_isolation_probe.py"
    names = [name for _, name in _resolve_imports(fake, bad)]
    flagged = [n for n in names if _is_violation(n)]
    assert "backend.services.chat_service" in flagged
    assert "backend.llm.model_provider" in flagged
    assert "backend.services.auth_service" in flagged
    # And a legit read-only import is NOT flagged.
    assert not _is_violation("backend.database.users_repo")
    assert not _is_violation("sqlite3")
    assert not _is_violation("backend.services.feed_v2.db")


if __name__ == "__main__":
    v = find_violations()
    if v:
        print("VIOLATIONS:")
        for f, ln, name in v:
            print(f"  {f}:{ln} imports {name}")
        raise SystemExit(1)
    print(f"OK — scanned {len(list(FEED_V2_DIR.rglob('*.py')))} feed_v2 files, no forbidden imports.")
