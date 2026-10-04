"""UI motion checks. Need the dev servers (see the plan's Global Constraints);
skipped otherwise so a bare `pytest` never fails on them.

    pytest scripts/ui_motion -q
"""
import json

import pytest
from playwright.sync_api import sync_playwright

from .session import OUT, THEMES, WIDTHS, new_page, normalize, run_flows, servers_up

pytestmark = pytest.mark.skipif(not servers_up(), reason="needs npm run dev + backend on :8000")

BASELINE = OUT / "baseline" / "console.json"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", list(WIDTHS))
def test_flows_add_no_console_errors(browser, theme, width):
    page, errors = new_page(browser, theme, width)
    run_flows(page, width)
    new = normalize(errors) - set(json.loads(BASELINE.read_text()))
    page.context.close()
    assert not new, f"new console errors: {sorted(new)}"


from .session import goto, running_transform_animations


def _open_and_sample(page):
    goto(page, "/feed")
    page.keyboard.press("Control+k")
    page.wait_for_timeout(60)
    first = running_transform_animations(page)
    page.keyboard.press("Escape")
    goto(page, "/dashboard", settle=60)
    return first + running_transform_animations(page)


from .session import APP_URL


def test_keyboard_focus_is_visible(browser):
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/feed")
    seen = []
    for _ in range(6):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("""() => { const s = getComputedStyle(document.activeElement)
            return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 || s.boxShadow !== 'none' }"""))
    page.context.close()
    assert all(seen), seen


def swipe(locator, dx, dy):
    """Synthetic touch drag starting 300px down the element — exercises
    useSwipeDismiss's own pointer handling, which is all the gesture is."""
    locator.evaluate("""(el, [dx, dy]) => {
      const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 300
      const ev = (type, cx, cy) => el.dispatchEvent(new PointerEvent(type,
        { pointerType: 'touch', clientX: cx, clientY: cy, bubbles: true, isPrimary: true }))
      ev('pointerdown', x, y)
      for (let i = 1; i <= 6; i++) ev('pointermove', x + dx * i / 6, y + dy * i / 6)
      ev('pointerup', x + dx, y + dy)
    }""", [dx, dy])


def test_section_switch_enters(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    page.get_by_role("link", name="Dashboard", exact=True).first.click()
    page.wait_for_timeout(30)
    entering = page.evaluate("""() => document.getAnimations().some(a =>
        a.transitionProperty === 'opacity' && a.effect.target.classList.contains('u-section'))""")
    page.context.close()
    assert entering


def test_nav_pill_follows_the_active_section(browser):
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/feed")
    page.get_by_role("link", name="Chat", exact=True).first.click()
    page.wait_for_timeout(700)
    pills = page.locator("[data-nav-pill]")
    inside_active = pills.first.evaluate("p => p.closest('a').getAttribute('aria-current') === 'page'")
    count = pills.count()
    page.context.close()
    assert count == 1 and inside_active


def _open_drawer(browser):
    page, _ = new_page(browser, "light", "phone")
    goto(page, "/feed")
    page.get_by_label("Open navigation").click()
    page.wait_for_timeout(600)
    return page, page.locator("aside")


def test_drawer_swipe_left_closes(browser):
    page, aside = _open_drawer(browser)
    swipe(aside, -160, 6)
    page.wait_for_timeout(300)
    state = aside.get_attribute("data-open")
    page.context.close()
    assert state == "false"


def test_drawer_vertical_scroll_keeps_it_open(browser):
    """Review Focus 4."""
    page, aside = _open_drawer(browser)
    swipe(aside, -6, -180)
    page.wait_for_timeout(300)
    state = aside.get_attribute("data-open")
    page.context.close()
    assert state == "true"


def test_dialog_exit_plays_and_ignores_clicks(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    page.keyboard.press("Control+k")
    page.wait_for_timeout(500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(40)
    root = page.locator(".u-motion-managed")
    still_there = root.count() == 1
    blocked = still_there and root.first.evaluate("e => getComputedStyle(e).pointerEvents") == "none"
    page.wait_for_timeout(600)
    gone = page.locator(".u-motion-managed").count() == 0
    page.context.close()
    assert still_there and blocked and gone, (still_there, blocked, gone)


def test_small_dialog_is_bottom_sheet_on_phone(browser):
    page, _ = new_page(browser, "dark", "phone")
    goto(page, "/feed")
    page.get_by_title("Save to bookmarks").first.click()
    page.wait_for_timeout(800)
    box = page.locator(".u-sheet").first.bounding_box()
    handle = page.locator(".u-sheet-handle").first.is_visible()
    page.context.close()
    assert box and abs(box["y"] + box["height"] - 844) < 2 and box["width"] >= 389, box
    assert handle, "sheet handle hidden — nothing for a finger to drag"


def test_dialog_from_hovered_card_covers_viewport(browser):
    """Review Focus 1 — a lifted/tilted ancestor must never trap a fixed dialog."""
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    save = page.get_by_title("Save to bookmarks").first
    save.hover()
    page.wait_for_timeout(500)
    save.click()
    page.wait_for_timeout(700)
    box = page.locator(".u-motion-managed").first.bounding_box()
    page.context.close()
    assert box and abs(box["x"]) < 1 and abs(box["y"]) < 1 and box["width"] >= 1439 and box["height"] >= 899, box


import re as _re

DAY_BUTTON = _re.compile(r"^day \d+$", _re.I)


def test_menu_exits_and_pill_follows(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    page.get_by_role("button", name=DAY_BUTTON).first.click()
    page.wait_for_timeout(400)
    menu = page.locator(".u-menu").first
    menu.locator("button").first.hover()
    page.wait_for_timeout(100)
    pill_on = menu.get_attribute("data-pill") == "on"
    page.mouse.click(5, 300)
    page.wait_for_timeout(40)
    exiting = page.locator(".u-menu").count() == 1
    page.wait_for_timeout(500)
    gone = page.locator(".u-menu").count() == 0
    page.context.close()
    assert pill_on and exiting and gone, (pill_on, exiting, gone)


def test_rapid_toggle_leaves_one_menu(browser):
    """Review Focus 3."""
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/feed")
    trigger = page.get_by_role("button", name=DAY_BUTTON).first
    for _ in range(5):
        trigger.click(delay=10)
    page.wait_for_timeout(700)
    count = page.locator(".u-menu").count()
    page.context.close()
    assert count <= 1, count


def test_reading_card_lifts_on_hover_without_tilting(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    card = page.locator(".u-read-card").first
    card.hover()
    page.wait_for_timeout(600)
    style = card.evaluate("c => { const s = getComputedStyle(c); return [s.translate, s.rotate] }")
    page.context.close()
    assert style[0].endswith("-4px") and style[1] in ("none", "0deg"), style


def _mark_all(page, name):
    for _ in range(20):
        btn = page.get_by_role("button", name=name, exact=True)
        if not btn.count():
            return
        btn.first.click()
        page.wait_for_timeout(500)


def test_confetti_only_on_completion(browser):
    """Review Focus 5. Marks Day 1 read on the UI-check account, then puts it back."""
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    try:
        _mark_all(page, "Read")                    # start from all-unread
        goto(page, "/feed")
        _mark_all(page, "Mark as Read")
        on_complete = page.locator(".u-confetti").count()
        goto(page, "/feed")                        # reload a complete day
        on_load = page.locator(".u-confetti").count()
        page.get_by_role("button", name="Read", exact=True).first.click()
        page.wait_for_timeout(500)
        on_unmark = page.locator(".u-confetti").count()
    finally:
        _mark_all(page, "Read")
        page.context.close()
    assert (on_complete, on_load, on_unmark) == (1, 0, 0), (on_complete, on_load, on_unmark)


def test_new_messages_enter_history_does_not(browser):
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/chat")
    box = page.get_by_placeholder(_re.compile("Ask anything", _re.I))
    box.click()
    box.type("Why did Byzantium tax at the ports?")
    page.keyboard.press("Enter")
    page.get_by_text("choke points", exact=False).first.wait_for(timeout=15000)
    fresh = page.locator(".u-msg-in").count()
    page.context.close()
    assert fresh >= 2, fresh   # the question and the answer


def test_attachment_chip_enters_and_leaves(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/chat")
    page.locator('input[type="file"]').first.set_input_files(
        files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"ui motion check"}])
    chip = page.locator("[data-chip]").first
    chip.wait_for(timeout=10000)
    page.get_by_label("Remove attachment").first.click()
    page.wait_for_timeout(40)
    leaving = page.locator("[data-chip]").count() == 1
    page.wait_for_timeout(500)
    gone = page.locator("[data-chip]").count() == 0
    page.context.close()
    assert leaving and gone, (leaving, gone)


def test_dashboard_counts_and_draws(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/dashboard", settle=200)
    counters = page.locator("[data-countup]").count()
    drawing = page.evaluate("() => document.getAnimations().some(a => a.animationName === 'm-ring-draw')")
    page.context.close()
    assert counters >= 5 and drawing, (counters, drawing)


def test_sidebar_rows_are_layout_animated(browser):
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    # A Motion list item writes its resting values inline (opacity: 1) on the
    # wrapper — a plain div never has them.
    wrapped = page.evaluate("""() => [...document.querySelectorAll('aside .u-nudge')]
        .every(row => row.parentElement && row.parentElement.style.opacity === '1')""")
    nudges = page.locator("aside .u-nudge").count()
    page.context.close()
    assert nudges >= 1 and wrapped, (nudges, wrapped)


def test_no_button_spinners_left():
    from .session import ROOT
    src = ROOT / "frontend" / "src"
    offenders = []
    for f in src.rglob("*.jsx"):
        if f.name in ("GlobalSearch.jsx", "LandingPage.jsx"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "animate-spin" in text:
            offenders.append(f.name)
    assert not offenders, offenders


def test_login_card_springs_in(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(APP_URL + "/login")
    page.wait_for_timeout(100)
    rising = page.evaluate("() => document.getAnimations().some(a => a.animationName === 'm-rise')")
    ctx.close()
    assert rising


def test_bare_field_draws_no_inner_ring(browser):
    """A u-bare field sits inside a composer whose border already shows focus."""
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/chat")
    box = page.get_by_placeholder(_re.compile("Ask anything", _re.I))
    box.click()
    shadow = box.evaluate("e => e.matches(':focus-visible') && getComputedStyle(e).boxShadow")
    page.context.close()
    assert shadow == "none", shadow


# ── Final-review fix pass ─────────────────────────────────────────────────────

from .session import API_URL, STREAM_LINES


def _stream(lines):
    body = "\n".join(json.dumps(line) for line in lines) + "\n"
    return lambda r: r.fulfill(status=200, content_type="application/x-ndjson", body=body)


def _ask(page):
    box = page.get_by_placeholder(_re.compile("Ask anything", _re.I))
    box.click()
    box.type("Why did Byzantium tax at the ports?")
    page.keyboard.press("Enter")


def test_tool_call_sources_scroll(browser):
    """Review: the collapse preset's inline overflow:hidden beat overflow-y-auto."""
    page, _ = new_page(browser, "dark", "desktop")
    sources = [{"url": f"https://example.com/{i}", "title": f"Source {i}"} for i in range(10)]
    page.route(f"{API_URL}/chat/stream", _stream([
        STREAM_LINES[0],
        {"t": "status", "v": "Searching", "block_id": "t1", "tool": "web_search", "query": "byzantine ports"},
        {"t": "status", "v": "Found", "block_id": "t1", "tool": "web_search", "sources": sources},
        *STREAM_LINES[1:],
    ]))
    goto(page, "/chat")
    _ask(page)
    page.get_by_text("choke points", exact=False).first.wait_for(timeout=15000)
    page.get_by_text("10 sources").first.click()
    page.wait_for_timeout(900)
    scrolls = page.locator('a[href="https://example.com/0"]').evaluate(
        "a => { const box = a.parentElement; return box.scrollHeight > box.clientHeight"
        " && ['auto', 'scroll'].includes(getComputedStyle(box).overflowY) }")
    page.context.close()
    assert scrolls


def _eye_centre(page):
    b = page.get_by_label(_re.compile("^(Show|Hide) password$")).first.bounding_box()
    return b["y"] + b["height"] / 2


def test_centred_icon_button_holds_still(browser):
    """Review: the press rule set `transform`, erasing -translate-y-1/2 centring."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(APP_URL + "/login")
    eye = page.get_by_label("Show password").first
    eye.wait_for(timeout=30000)
    page.wait_for_timeout(800)
    rest = _eye_centre(page)
    eye.hover()
    page.wait_for_timeout(300)
    hover = _eye_centre(page)
    page.mouse.down()
    page.wait_for_timeout(300)
    pressed = _eye_centre(page)
    page.mouse.up()
    ctx.close()
    assert max(abs(hover - rest), abs(pressed - rest)) < 1, (rest, hover, pressed)


def test_finished_entrances_hold_no_transform(browser):
    """Review: from-only entrances with fill `both` kept a transform in effect for
    good, so the element trapped `position: fixed` children."""
    page, _ = new_page(browser, "light", "desktop")
    held = []
    for path in ("/dashboard", "/feed"):
        goto(page, path, settle=2500)
        held += page.evaluate("""() => document.getAnimations()
            .filter(a => a.playState === 'finished' && a.effect && a.effect.getComputedTiming().progress !== null && a.effect.getKeyframes()
                .some(k => ['translate', 'scale', 'rotate', 'transform'].some(p => p in k)))
            .map(a => (a.animationName || 'waapi') + ' on ' + String(a.effect.target.className).slice(0, 40))""")
    page.context.close()
    assert not held, held[:6]


def test_fixed_day_pill_holds_still_on_section_switch(browser):
    """Review: the section's translate entry made it the containing block for
    fixed children (the feed's day pill) for 280ms."""
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/dashboard")
    page.get_by_role("link", name="Feed", exact=True).first.click()
    pill = page.get_by_role("button", name=DAY_BUTTON).first
    pill.wait_for(timeout=10000)
    page.wait_for_timeout(20)
    early = pill.bounding_box()
    page.wait_for_timeout(800)
    late = pill.bounding_box()
    page.context.close()
    assert abs(early["x"] - late["x"]) < 1 and abs(early["y"] - late["y"]) < 1, (early, late)


def test_project_delete_sheet_swipes_down(browser):
    """Review: useSwipeDismiss read its ref once, before the sheet existed, when the
    hook lives in an always-mounted parent (ProjectsPage). Swipe = cancel; nothing
    is deleted."""
    page, _ = new_page(browser, "light", "phone")
    goto(page, "/feed")
    page.locator('[aria-label="More options"]:visible').first.click()
    page.wait_for_timeout(400)
    page.locator(".u-menu button", has_text="Delete project").first.click()
    sheet = page.locator(".u-sheet").first
    sheet.wait_for(timeout=5000)
    page.wait_for_timeout(700)
    page.locator(".u-sheet-handle").first.evaluate("""h => {
      const r = h.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2
      const ev = (type, cy) => h.dispatchEvent(new PointerEvent(type,
        { pointerType: 'touch', clientX: x, clientY: cy, bubbles: true, isPrimary: true }))
      ev('pointerdown', y)
      for (let i = 1; i <= 6; i++) ev('pointermove', y + 40 * i)
      ev('pointerup', y + 240)
    }""")
    page.wait_for_timeout(700)
    open_after = page.locator(".u-sheet").count()
    page.context.close()
    assert open_after == 0


def test_phone_shows_plates(browser):
    """Review: landing.css hides .lp-plate below 768px; the app's plates are meant
    to show on capable phones (the harness host reports few cores, so pin one)."""
    page, _ = new_page(browser, "dark", "phone")
    page.context.add_init_script("""Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 })
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 })""")
    goto(page, "/bookmarks")
    lite = page.evaluate("document.documentElement.hasAttribute('data-motion-lite')")
    shown = page.evaluate("""() => [...document.querySelectorAll('.lp-plate.u-plate')]
        .some(p => getComputedStyle(p).display !== 'none' && p.getBoundingClientRect().width > 0)""")
    page.context.close()
    assert not lite and shown, (lite, shown)


def test_legacy_draws_motion_colours(browser):
    """Legacy leaves most palette vars unset; a bare var() blanked the progress
    fill and the keyboard focus ring there."""
    page, _ = new_page(browser, "legacy", "desktop")
    goto(page, "/feed")
    fill = page.locator(".u-progress-fill").first.evaluate("f => getComputedStyle(f).backgroundImage")
    page.keyboard.press("Tab")
    ring = page.evaluate("() => { const s = getComputedStyle(document.activeElement); return s.outlineStyle + ' ' + s.outlineWidth }")
    page.context.close()
    assert fill.startswith("linear-gradient") and ring.startswith("solid"), (fill, ring)


def test_animations_run_even_with_device_reduce_motion(browser):
    """The app always animates: no Motion setting, and the device's own
    reduce-motion preference is not followed (user decision 2026-10-02)."""
    page, _ = new_page(browser, "light", "desktop", reduced_os=True)
    entering = bool(_open_and_sample(page))          # search palette + dashboard both move
    page.locator("aside button", has_text="UI Check").first.click()
    page.wait_for_timeout(500)
    control = page.get_by_role("radiogroup", name="Motion").count()
    page.context.close()
    assert entering and control == 0, (entering, control)
