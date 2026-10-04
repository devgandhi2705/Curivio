"""Shared setup for the UI motion checks.

Who the browser is signed in as, which backend calls are faked so no model
quota is spent, which console errors count, and the scripted walk through
every flow the motion work must not break.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "ui_motion"
APP_URL = os.getenv("CURIVIO_UI_URL", "http://localhost:5173")
API_URL = os.getenv("CURIVIO_API_URL", "http://localhost:8000")
UI_EMAIL = os.getenv("CURIVIO_UI_EMAIL", "uicheck@local.test")

THEMES = ("light", "dark", "legacy")
WIDTHS = {"phone": (390, 844), "desktop": (1440, 900)}
SCREENS = {
    "feed": "/feed",
    "chat": "/chat",
    "dashboard": "/dashboard",
    "bookmarks": "/bookmarks",
    "read-later": "/read-later",
}

# The chat stream and the upload endpoint are the only flows that would spend
# model quota, so both are answered here in the backend's own NDJSON shape.
STREAM_LINES = [
    {"t": "status", "v": "Generating response…"},
    {"t": "chunk", "v": "Ports were choke points: one customs post could see every cargo, ", "seq": 1, "block_id": "b1"},
    {"t": "chunk", "v": "so tax there was cheap to enforce and hard to dodge.", "seq": 2, "block_id": "b1"},
    {"t": "done", "title": "Byzantine ports"},
]
UPLOAD_DONE = {
    "t": "done", "uri": "doc://ui-motion-check", "mime_type": "text/plain",
    "filename": "notes.txt", "size_bytes": 15, "expires_at": "2099-01-01T00:00:00Z",
}

# Network failures are the backend's business (rate limits, admin 404s), not
# the UI's; the other two are dev-only banners.
NOISE = ("Failed to load resource", "React Router Future Flag", "Download the React DevTools")


def servers_up() -> bool:
    try:
        urlopen(f"{API_URL}/health", timeout=3).read()
        urlopen(APP_URL, timeout=3).read()
        return True
    except OSError:
        return False


def session_storage() -> dict:
    """Token + user for the local UI-check account, minted the way login does."""
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from backend.services.auth_service import create_access_token, get_user_by_email

    user = get_user_by_email(UI_EMAIL)
    if not user:
        raise RuntimeError(f"No local account {UI_EMAIL}. Sign up once in the app with that email.")
    # A returning user's browser: onboarding already done, sidebar expanded.
    # Without these a fresh context opens the first-run wizard over the feed.
    return {
        "ra_token": create_access_token(user["user_id"]),
        "ra_user": json.dumps(user),
        f"ra_onboarding_done_{user['user_id']}": "1",
        "sidebar_collapsed": "false",
    }


# The backend rate-limits per IP (projects endpoints: 30/minute), and a run
# reloads the feed far faster than that. Real reads are fetched once per run
# and replayed; any write clears the cache so later reads see its effect.
# Streams pass straight through — buffering one would hang the page.
_READS: dict[str, tuple[int, dict, bytes]] = {}
_DROP_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def _read_through(route) -> None:
    try:
        _serve(route)
    except Exception as e:  # a test closed its context mid-request: nothing left to answer
        if "disposed" not in str(e) and "closed" not in str(e):
            raise


def _serve(route) -> None:
    req = route.request
    if req.method != "GET":
        _READS.clear()
        route.continue_()
        return
    if "stream" in req.url or "events" in req.url:
        route.continue_()
        return
    hit = _READS.get(req.url)
    if hit is None:
        resp = route.fetch()
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in _DROP_HEADERS}
        hit = (resp.status, headers, resp.body())
        if resp.status != 429 and resp.status < 500:
            _READS[req.url] = hit
    status, headers, body = hit
    route.fulfill(status=status, headers=headers, body=body)


def stub_llm(page) -> None:
    def ndjson(lines):
        return "\n".join(json.dumps(line) for line in lines) + "\n"

    # Registered first so the specific stubs below win (Playwright tries the
    # most recently registered route first).
    page.route(f"{API_URL}/**", _read_through)

    page.route(f"{API_URL}/chat/stream", lambda r: r.fulfill(
        status=200, content_type="application/x-ndjson", body=ndjson(STREAM_LINES)))
    page.route(f"{API_URL}/chat/upload", lambda r: r.fulfill(
        status=200, content_type="application/x-ndjson", body=ndjson([UPLOAD_DONE])))


def new_page(browser, theme="light", width="desktop", reduced_os=False):
    w, h = WIDTHS[width]
    phone = width == "phone"
    ctx = browser.new_context(
        viewport={"width": w, "height": h},
        has_touch=phone,
        is_mobile=phone,
        reduced_motion="reduce" if reduced_os else "no-preference",
    )
    store = session_storage()
    store["curivio.ui"] = theme
    ctx.add_init_script(
        "(s => { for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v) })("
        + json.dumps(store) + ")"
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    stub_llm(page)
    return page, errors


def normalize(errors) -> set[str]:
    out = set()
    for e in errors:
        if any(n in e for n in NOISE):
            continue
        e = re.sub(r"https?://\S+", "<url>", e)
        e = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", e)
        e = re.sub(r"\d+", "<n>", e)
        out.add(e[:300])
    return out


def goto(page, path, settle=1800):
    # A fresh context makes Vite's dev server send every module uncached; the
    # shell can take ~6s to appear, so wait for it before the settle period.
    page.goto(APP_URL + path)
    page.wait_for_selector("aside", state="attached", timeout=30000)
    page.wait_for_timeout(settle)


def run_flows(page, width) -> None:
    """Every flow the motion work touches. Optional steps are skipped when the
    account has nothing to show for them (e.g. no day dropdown yet)."""
    for path in SCREENS.values():
        goto(page, path)

    goto(page, "/feed")
    day = page.get_by_role("button", name=re.compile(r"^day \d+$", re.I))
    if day.count():
        day.first.click()
        page.wait_for_timeout(400)
        page.mouse.click(5, 300)
        page.wait_for_timeout(400)

    page.keyboard.press("Control+k")
    search = page.get_by_placeholder(re.compile("^Search cards"))
    search.fill("byz")
    page.wait_for_timeout(700)
    search.press("Escape")
    search.wait_for(state="detached", timeout=5000)

    if width == "desktop":
        page.locator("aside button", has_text="UI Check").first.click()
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.mouse.click(900, 500)
        page.wait_for_timeout(400)
    else:
        page.get_by_label("Open navigation").click()
        page.wait_for_timeout(700)
        page.get_by_label("Close sidebar").click()
        page.wait_for_timeout(700)

    goto(page, "/chat")
    box = page.get_by_placeholder(re.compile("Ask anything", re.I))
    box.click()
    box.type("Why did Byzantium tax at the ports?")
    page.keyboard.press("Enter")
    page.get_by_text("choke points", exact=False).first.wait_for(timeout=15000)
    page.locator('input[type="file"]').first.set_input_files(
        files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"ui motion check"}])
    page.get_by_text("notes.txt").first.wait_for(timeout=10000)


TRANSFORMISH = ("transform", "translate", "scale", "rotate")


def running_transform_animations(page) -> list[dict]:
    """Running CSS animations/transitions or WAAPI animations that move things."""
    return page.evaluate(
        """(props) => document.getAnimations()
            .filter(a => a.playState === 'running')
            .map(a => {
              const kf = a.effect && a.effect.getKeyframes ? a.effect.getKeyframes() : []
              const keys = new Set(kf.flatMap(k => Object.keys(k)))
              if (a.transitionProperty) keys.add(a.transitionProperty)
              const timing = a.effect ? a.effect.getComputedTiming() : {}
              return { keys: [...keys], iterations: timing.iterations, duration: timing.duration,
                       target: a.effect && a.effect.target ? a.effect.target.className?.baseVal ?? a.effect.target.className : '' }
            })
            .filter(a => a.keys.some(k => props.includes(k)) || a.iterations === Infinity || a.duration > 150)""",
        list(TRANSFORMISH),
    )
