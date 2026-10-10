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


def _open_reader(browser, width):
    page, _ = new_page(browser, "dark", width)
    goto(page, "/feed")
    page.get_by_label("Reading mode").first.click()
    page.wait_for_selector(".u-reader-card", timeout=15000)
    page.wait_for_timeout(1200)
    return page


def test_reader_phone_tucks_reference_and_docks_ai_actions(browser):
    """Phone reading mode: sources and discussions start closed, the card's
    actions sit in one row, and Ask / Explain live in the bottom dock."""
    page = _open_reader(browser, "phone")
    card = page.locator(".u-reader-card")
    link = card.locator(".u-rc-sources a").first
    sources_closed = not link.is_visible()
    card.locator(".u-rc-sources button[aria-expanded]").click()
    sources_open = link.is_visible()
    related = card.locator(".u-rc-related button[aria-expanded]").get_attribute("aria-expanded")
    rows = card.locator(".u-rc-actions > *").evaluate_all(
        "els => new Set(els.filter(e => e.getClientRects().length).map(e => Math.round(e.getBoundingClientRect().top))).size")
    rail_ask = card.get_by_role("button", name="Ask about this").is_visible()
    dock = page.locator(".u-reader footer")
    dock_ask = dock.get_by_role("button", name="Ask", exact=True).is_visible()
    dock_explain = dock.get_by_role("button", name="Explain simply").is_visible()
    page.context.close()
    assert (sources_closed, sources_open, related, rows, rail_ask, dock_ask, dock_explain) == (
        True, True, "false", 1, False, True, True)


def test_reader_desktop_keeps_reference_open_and_actions_in_rail(browser):
    page = _open_reader(browser, "desktop")
    card = page.locator(".u-reader-card")
    sources_open = card.locator(".u-rc-sources a").first.is_visible()
    related = card.locator(".u-rc-related button[aria-expanded]").get_attribute("aria-expanded")
    rail_ask = card.get_by_role("button", name="Ask about this").is_visible()
    dock_ask = page.locator(".u-reader footer").get_by_role("button", name="Ask", exact=True).count()
    page.context.close()
    assert (sources_open, related, rail_ask, dock_ask) == (True, "true", True, 0)


def test_reader_settings_brightness_slider_and_transition_preview(browser):
    """Brightness is a slider that dims the slides; the Transition picker has a
    looping preview in place of the old Transition time box."""
    page = _open_reader(browser, "desktop")
    _wake(page)
    page.locator(".u-reader header").get_by_title("Reading settings").click()
    panel = page.get_by_role("dialog", name="Reading settings")
    dim = panel.get_by_label("Brightness")
    got = {"slider": dim.get_attribute("type") == "range"}
    dim.fill("60")
    got["dims"] = "brightness(0.6)" in page.locator(".u-reader .overflow-hidden").first.evaluate("e => e.style.filter")
    got["no_time_box"] = panel.get_by_text("Transition time").count() == 0
    panel.get_by_role("radio", name="Fade").click()
    seen = set()
    for _ in range(12):                                          # the loop turns every 1.8s
        seen.update(t for t in ("Article 1", "Article 2") if panel.get_by_text(t, exact=True).count())
        page.wait_for_timeout(300)
    got["preview_turns"] = seen == {"Article 1", "Article 2"}
    panel.get_by_role("button", name="Reset", exact=True).click()
    page.context.close()
    assert all(got.values()), got


def _reader_title(page):
    return page.locator(".u-reader-card .u-read-title").inner_text()


def _wake(page):
    """The reader's toolbar and dock tuck away after 2.5s still (autoHide is
    the default); any movement brings them back, as a touch would."""
    page.mouse.move(5, 5)
    page.mouse.move(6, 6)
    page.wait_for_timeout(150)


def _next_article(page):
    _wake(page)
    page.locator(".u-reader footer").get_by_label("Next article").click()
    page.wait_for_timeout(900)


def test_reader_phone_offline_mark_and_grouped_reference(browser):
    """Offline status sits on the "Article n of m" line; Sources and
    Discussions are one grouped card."""
    page = _open_reader(browser, "phone")
    eyebrow = page.locator(".u-reader-card .u-rc-eyebrow").inner_text()
    meta = page.locator(".u-reader-card .u-rc-meta").inner_text()
    grouped = page.locator(".u-reader-card .u-rc-ref").evaluate(
        "g => !!(g.querySelector('.u-rc-sources') && g.querySelector('.u-rc-related'))")
    page.context.close()
    assert ("offline" in eyebrow.lower(), "offline" in meta.lower(), grouped) == (True, False, True)


def test_reader_url_survives_refresh(browser):
    page = _open_reader(browser, "phone")
    _next_article(page)
    title, url = _reader_title(page), page.url
    page.reload()
    page.wait_for_selector(".u-reader-card", timeout=30000)
    page.wait_for_timeout(1200)
    title_after = _reader_title(page)
    _wake(page)
    page.locator(".u-reader header").get_by_title("Exit reading mode (Esc)").click()
    page.wait_for_timeout(900)
    exited, still_open = page.url, page.locator(".u-reader").count()
    page.context.close()
    assert ("read=1" in url, title_after, "read=" in exited, still_open) == (True, title, False, 0)


def test_chat_from_reader_links_back_to_the_article(browser):
    """Ask from the reader: chat's URL names where it came from and survives
    the first send and a reload; its back link reopens the reader on the same
    article. Reopened without ?from (chat history), the backend's record of the
    source still links back to the card."""
    page = _open_reader(browser, "phone")
    # The chat stream is faked, so its session never reaches the database and
    # the backend (rightly) refuses to link it to a card. Stand in for the link
    # store; the real routes are covered by tests/test_chat_feed_link_security.py
    # and TestChatSessionSourceEndpoint.
    saved = {}

    def link_store(route):
        if route.request.method != "POST":
            return route.fallback()
        saved.update(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"id": 1, **saved}))
    page.route(f"{API_URL}/feed-chat-links", link_store)
    page.route(_re.compile(r".*/chat/sessions/[^/?]+/source$"), lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({k: saved.get(k) for k in ("project_id", "insight_id", "article_key", "article_title")} if saved else None)))
    _next_article(page)
    title = _reader_title(page)
    _wake(page)
    page.locator(".u-reader footer").get_by_role("button", name="Ask", exact=True).click()
    page.wait_for_url("**/chat?from=*", timeout=10000)
    box = page.get_by_placeholder(_re.compile("Ask anything", _re.I)).first
    box.fill("Why does this matter?")
    page.keyboard.press("Enter")
    page.get_by_text("choke points", exact=False).first.wait_for(timeout=15000)
    page.wait_for_url(_re.compile(r"/chat/[^/?]+\?from="), timeout=10000)
    page.wait_for_timeout(800)   # the feed→chat link is saved after the stream ends
    from_url = page.url[len(APP_URL):]

    goto(page, from_url.split("?")[0])
    back = page.get_by_role("link", name=_re.compile("Back to article", _re.I))
    back.wait_for(timeout=10000)
    history_href = back.get_attribute("href")

    goto(page, from_url)
    page.get_by_role("link", name=_re.compile("Back to article", _re.I)).click()
    page.wait_for_selector(".u-reader-card", timeout=15000)
    page.wait_for_timeout(1200)
    title_back = _reader_title(page)
    page.context.close()
    assert (title_back, history_href.startswith("/feed/"), "read=" in history_href) == (title, True, False)


def test_unsent_card_context_does_not_follow_into_a_later_chat(browser):
    """Ask from a card, go back without asking, then open Chat normally: the
    card's "Asking about" header must be gone (the chat view stays mounted)."""
    page = _open_reader(browser, "desktop")
    _wake(page)
    page.locator(".u-reader-card").get_by_role("button", name="Ask about this").click()
    page.wait_for_url("**/chat?from=*", timeout=10000)
    page.get_by_text("Asking about", exact=False).first.wait_for(timeout=10000)
    page.get_by_role("link", name=_re.compile("Back to article", _re.I)).first.click()
    page.wait_for_selector(".u-reader-card", timeout=15000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    page.locator("aside").get_by_role("link", name="Chat", exact=True).first.click()
    page.wait_for_timeout(1200)
    still = page.get_by_text("Asking about", exact=False).count()
    page.context.close()
    assert still == 0


def _select_card_text(page, end=12):
    """Select the first words of a feed card the way a reader would, which is
    what opens Unpack (useTextSelection listens for mouseup)."""
    page.evaluate("""() => {
      const p = [...document.querySelectorAll('.u-read-card p')].find(e => e.textContent.trim().length > 40)
      const node = [...p.childNodes].find(n => n.nodeType === 3 && n.textContent.trim().length > 20)
      const r = document.createRange(); r.setStart(node, 0); r.setEnd(node, END)
      const s = getSelection(); s.removeAllRanges(); s.addRange(r)
      document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }""".replace("END", str(end)))
    page.locator("[data-unpack-popover]").wait_for(timeout=5000)


def _running(page, name):
    return page.evaluate(f"() => document.getAnimations().some(a => a.animationName === '{name}')")


def _open_share(browser, width):
    page, _ = new_page(browser, "dark", width)
    page.route(f"{API_URL}/share/create", _ok({"token": "abc123def456ghi789"}))
    if width == "phone":                          # a phone browser with a native share sheet
        page.add_init_script("navigator.share = () => Promise.resolve()")
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    goto(page, "/feed")
    card = page.locator(".u-read-card").first
    title = card.locator("h3, h2").first.inner_text().strip()
    card.get_by_role("button", name="Share", exact=True).click()
    pop = page.locator("[data-share-popover]")
    pop.wait_for(timeout=5000)
    page.wait_for_timeout(400)
    return page, pop, title


def _ok(body):
    return lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _admin_page(browser, put_status=204):
    """/admin/calls with every admin endpoint stubbed (the harness account isn't an
    admin): one two-call operation group and one single call."""
    page, _ = new_page(browser, "dark", "desktop")
    seen = {"grouped": [], "put": [], "delete": []}
    groups = [
        {"trace_id": "tA", "surface": "explain", "action_type": "explain", "started_at": "2026-10-01 10:00:00",
         "ended_at": "2026-10-01 10:00:05", "row_count": 2, "all_succeeded": True, "has_web_search": False,
         "user_email": "a@example.com", "op_latency_ms": 240, "op_tokens": 20, "starred": False,
         "rows": [_admin_row(1, "tA"), _admin_row(2, "tA")]},
        {"trace_id": None, "surface": "explain", "action_type": "explain", "started_at": "2026-10-01 09:00:00",
         "ended_at": "2026-10-01 09:00:01", "row_count": 1, "all_succeeded": True, "has_web_search": False,
         "user_email": "a@example.com", "op_latency_ms": 120, "op_tokens": 10, "starred": True,
         "rows": [_admin_row(3, None)]},
    ]
    summary = {"total_calls": 3, "success_count": 3, "error_count": 0, "success_rate": 1.0, "total_tokens": 30,
               "avg_latency_ms": 120, "by_call_type": [], "by_model": [], "by_surface": [], "by_error_type": []}
    ops = {"total_operations": 2, "succeeded_operations": 2, "failed_operations": 0,
           "operation_success_rate": 1.0, "avg_latency_per_operation_ms": 180}

    def admin(r):
        url = r.request.url
        if "/admin/stars" in url:
            seen["put" if r.request.method == "PUT" else "delete"].append(r.request.post_data or url)
            return r.fulfill(status=put_status, body="" if put_status == 204 else '{"detail": "nope"}',
                             content_type="application/json")
        if "/admin/calls/grouped" in url:
            seen["grouped"].append(url)
            return _ok({"total": 2, "limit": 20, "offset": 0, "groups": groups})(r)
        if "/admin/operations/summary" in url:
            return _ok(ops)(r)
        if "/admin/summary" in url:
            return _ok(summary)(r)
        if "/admin/calls/volume" in url:
            return _ok({"total": 3, "granularity": "day", "by_day": []})(r)
        if "/admin/projects" in url:
            return _ok({"projects": []})(r)
        return _ok({})(r)
    page.route(f"{API_URL}/admin/**", admin)
    goto(page, "/admin/calls")
    page.get_by_role("button", name="Star this operation").first.wait_for(timeout=10000)
    return page, seen


def test_admin_rows_can_be_starred_and_filtered(browser):
    page, seen = _admin_page(browser)
    op = page.get_by_role("button", name="Star this operation").first
    single = page.get_by_role("button", name="Star this call").first
    initial = (op.get_attribute("aria-pressed"), single.get_attribute("aria-pressed"))
    op.click()
    page.wait_for_timeout(200)
    after = op.get_attribute("aria-pressed")
    body = seen["put"][0] if seen["put"] else None
    expanded_rows_have_stars = None
    page.get_by_text("2 calls").first.click()                     # expand the group
    page.wait_for_timeout(300)
    expanded_rows_have_stars = page.get_by_role("button", name="Star this call").count() == 3
    page.get_by_label("★ Starred only").check()
    page.wait_for_timeout(500)
    filtered = any("starred=true" in u for u in seen["grouped"])
    page.context.close()
    got = dict(initial=initial == ("false", "true"), starred=after == "true",
               body=bool(body) and json.loads(body) == {"kind": "group", "key": "tA"},
               nested=expanded_rows_have_stars, filtered=filtered)
    assert all(got.values()), got


def test_admin_star_reverts_when_saving_fails(browser):
    page, _ = _admin_page(browser, put_status=500)
    op = page.get_by_role("button", name="Star this operation").first
    op.click()
    page.wait_for_timeout(600)
    pressed = op.get_attribute("aria-pressed")
    alert = page.get_by_role("alert").count()
    page.context.close()
    assert pressed == "false" and alert == 1, (pressed, alert)


@pytest.mark.parametrize("width", list(WIDTHS))
def test_feed_reads_at_reading_sizes(browser, width):
    """The feed's reading scale: serif titles above a 16px summary, running
    text at 14px or more, and a column narrow enough for ~75-character lines."""
    page, _ = new_page(browser, "dark", width)
    goto(page, "/feed")
    got = page.evaluate("""() => {
        const card = document.querySelector('.u-read-card')
        const px = el => parseFloat(getComputedStyle(el).fontSize)
        const title = card.querySelector('h3'), lead = card.querySelector('.u-read-lead')
        const body = [...card.querySelectorAll('p')].filter(p => p.closest('.u-read-card') === card && p.textContent.length > 40)
        return {
            serif: getComputedStyle(title).fontFamily.includes('Newsreader'),
            title_over_lead: px(title) > px(lead),
            lead: px(lead) >= 16,
            body: body.every(p => px(p) >= 14),
            column: card.getBoundingClientRect().width <= 720,
        }
    }""")
    page.context.close()
    assert all(got.values()), got


def test_next_day_is_generated_from_the_day_menu(browser):
    """The generate button moved from the bottom of the newest day into the Day
    menu. Marks the UI-check account's newest day read, then puts it back; the
    generate call itself is stubbed, so no package is really built."""
    page, _ = new_page(browser, "light", "desktop")
    posts = []
    page.route(f"{API_URL}/projects/*/insights/generate",
               lambda r: (posts.append(r.request.url), _ok({"id": 999999, "day_number": 99, "generated_at": "2026-10-03T00:00:00",
                                                           "status": "generating"})(r)))
    page.route(f"{API_URL}/projects/*/insights/999999/status", _ok({"status": "generating", "stage": "searching"}))
    goto(page, "/feed")
    day = page.get_by_role("button", name=DAY_BUTTON).first
    got = {}
    try:
        _mark_all(page, "Read")                                   # start from all-unread
        got["no_bottom_button"] = page.get_by_role("button", name=_re.compile(r"^generate day", _re.I)).count() == 0
        got["no_dot_when_locked"] = day.get_attribute("data-next") == "locked"
        day.click()
        page.wait_for_timeout(400)
        row = page.locator(".u-menu").get_by_role("button", name=GENERATE_ROW)
        got["locked_row"] = row.is_disabled() and "to unlock" in row.inner_text()
        page.mouse.click(5, 300)
        page.wait_for_timeout(500)

        _mark_all(page, "Mark as Read")
        got["dot_when_ready"] = day.get_attribute("data-next") == "ready"
        page.get_by_role("button", name=_re.compile(r"unlocked", _re.I)).click()  # the progress bar's nudge opens the menu
        page.wait_for_timeout(400)
        row = page.locator(".u-menu").get_by_role("button", name=GENERATE_ROW)
        got["ready_row"] = row.is_enabled()
        row.click()
        page.locator(".u-menu").get_by_role("button", name="Yes").click()
        page.wait_for_timeout(6500)                               # one status poll
        got["posted"] = len(posts) == 1
        # A later day gets Day 1's progress view, as one more stop in the Day
        # menu: the pill stays, and every built day is a click away.
        bg = page.get_by_role("button", name="Continue in background")
        got["progress_view"] = bg.is_visible() and "scanning today" in page.locator("main").inner_text().lower()
        got["pill_stays"] = day.is_visible() and day.get_attribute("data-next") == "building"
        got["no_reader_on_progress"] = page.get_by_role("button", name="Reading mode").count() == 0
        day.click()
        page.wait_for_timeout(400)
        got["building_row"] = "scanning sources" in page.locator(".u-menu").inner_text().lower()
        page.locator(".u-menu button").nth(1).click()             # the built day
        page.wait_for_timeout(600)
        got["day_back"] = bg.count() == 0 and page.get_by_role("button", name="Reading mode").is_visible()
        got["strip"] = page.get_by_text("Still building your next lesson").is_visible()
        day.click()
        page.wait_for_timeout(400)
        page.locator(".u-menu").get_by_role("button", name=GENERATE_ROW).click()
        page.wait_for_timeout(600)
        got["progress_again"] = bg.is_visible()
    finally:
        page.context.close()
    page, _ = new_page(browser, "light", "desktop")              # a fresh page: the stubbed run isn't polled any more
    goto(page, "/feed")
    _mark_all(page, "Read")
    page.context.close()
    assert all(got.values()), got


ISO_ID = "ui-iso-project"


def _with_second_project(page):
    """Adds an empty stub project beside the account's real one."""
    def projects(route):
        real = json.loads(route.fetch().text())
        fake = {**real[0], "project_id": ISO_ID, "name": "Iso Check", "insight_count": 0,
                "last_insight_at": None, "last_package_headline": None}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(real + [fake]))

    def iso(route):
        url = route.request.url
        if "/progression" in url:
            route.fulfill(status=404, content_type="application/json", body="{}")
        elif "/journey-preview" in url:
            _ok({"planned": False})(route)
        else:
            _ok([])(route)
    page.route(f"{API_URL}/projects", projects)
    page.route(f"{API_URL}/projects/{ISO_ID}/**", iso)


def test_a_run_stays_with_its_own_project(browser):
    """A run in one project shows nothing in another (no progress view, strip
    or Building pill), and when it lands there a toast offers to open it."""
    page, _ = new_page(browser, "dark", "desktop")
    _with_second_project(page)
    status = {"v": "generating"}
    page.route(f"{API_URL}/projects/*/insights/generate",
               _ok({"id": 999999, "day_number": 99, "generated_at": "2026-10-03T00:00:00", "status": "generating"}))
    page.route(f"{API_URL}/projects/*/insights/999999/status",
               lambda r: _ok({"status": status["v"], "stage": "searching"})(r))
    goto(page, "/feed")
    got = {}
    try:
        _mark_all(page, "Mark as Read")
        day = page.get_by_role("button", name=DAY_BUTTON).first
        day.click()
        page.wait_for_timeout(400)
        page.locator(".u-menu").get_by_role("button", name=GENERATE_ROW).click()
        page.locator(".u-menu").get_by_role("button", name="Yes").click()
        page.wait_for_timeout(800)
        got["running"] = page.get_by_role("button", name="Continue in background").is_visible()

        page.locator("aside").get_by_text("Iso Check", exact=True).click()
        page.wait_for_timeout(1500)
        main = page.locator("main").inner_text()
        got["other_is_idle"] = "Generate Day 1" in main and "Continue in background" not in main \
            and "Still building" not in main

        status["v"] = "done"
        page.wait_for_timeout(6500)                               # one status poll
        toast = page.get_by_role("status").filter(has_text="is ready")
        got["toast"] = toast.is_visible() and "Byzantine Trade Routes" in toast.inner_text()
        got["still_here"] = "Generate Day 1" in page.locator("main").inner_text()
        toast.get_by_role("button", name="Open").click()
        page.wait_for_timeout(1500)
        got["opened"] = "/feed/" in page.url and ISO_ID not in page.url and toast.count() == 0
    finally:
        page.context.close()
    page, _ = new_page(browser, "light", "desktop")
    goto(page, "/feed")
    _mark_all(page, "Read")
    page.context.close()
    assert all(got.values()), got


def test_share_on_a_phone_hands_off_to_the_native_sheet(browser):
    page, pop, _ = _open_share(browser, "phone")
    got = {"no_platform_grid": pop.get_by_role("link").count() == 0,
           "native": pop.get_by_role("button", name=_re.compile("share to apps", _re.I)).count() == 1}
    page.context.close()
    assert all(got.values()), got


def test_share_opens_on_a_preview_of_what_is_shared(browser):
    page, pop, title = _open_share(browser, "desktop")
    got = {"preview": title[:30] in pop.inner_text(), "url": "/share/abc123" in pop.inner_text()}
    copy = pop.get_by_role("button", name=_re.compile("copy link", _re.I)).element_handle()  # its name changes
    copy.click()
    page.wait_for_timeout(200)
    got["copied"] = "Copied" in copy.inner_text()
    got["clipboard"] = page.evaluate("navigator.clipboard.readText()").endswith("/share/abc123def456ghi789")
    got["platforms"] = pop.get_by_role("link").count() == 7
    page.wait_for_timeout(2300)
    got["reverts"] = "Copy link" in copy.inner_text()
    page.context.close()
    assert all(got.values()), got


def test_unpack_popover_moves(browser):
    """Unpack gets the app's motion: a livelier menu, slides between steps with a
    Back arrow, wave dots then a word-by-word answer, an exit on close, and sound
    bars while Read Aloud plays. Every /unpack call is stubbed."""
    page, _ = new_page(browser, "dark", "desktop")
    held = []
    page.route(f"{API_URL}/unpack/explain", lambda r: held.append(r))
    page.route(f"{API_URL}/unpack/read-aloud", _ok({"term": "x", "audio_base64": "SUQzBAAAAAAA"}))
    goto(page, "/feed")
    _select_card_text(page)
    pop = page.locator("[data-unpack-popover]")
    menu = pop.locator(".u-menu")
    menu_ok = menu.count() == 1 and menu.locator(".u-hover-pill").count() == 1 \
        and menu.locator("button svg").count() == 3
    pop.get_by_role("button", name="Translate").click()
    page.wait_for_timeout(30)
    slid_fwd = _running(page, "m-slide-fwd")
    pop.get_by_role("button", name="Back").click()
    page.wait_for_timeout(30)
    slid_back = _running(page, "m-slide-back") and pop.get_by_role("button", name="Explain").count() == 1
    page.wait_for_timeout(500)
    pop.get_by_role("button", name="Explain").click()
    page.wait_for_timeout(300)
    waving = pop.locator(".u-wave").count() == 1
    held[0].fulfill(status=200, content_type="application/x-ndjson", body=(
        json.dumps({"t": "chunk", "v": "Ports were choke points where every cargo passed."}) + "\n"
        + json.dumps({"t": "done", "meaning_in_context": "Ports were choke points where every cargo passed."}) + "\n"))
    page.wait_for_timeout(600)
    words = pop.locator(".u-word").count()
    page.keyboard.press("Escape")
    page.wait_for_timeout(40)
    leaving = page.locator("[data-unpack-popover]").count() == 1
    page.wait_for_timeout(600)
    gone = page.locator("[data-unpack-popover]").count() == 0
    _select_card_text(page, end=18)        # a new selection: the closed one's echo is ignored on purpose
    pop.get_by_role("button", name="Read Aloud").click()
    pop.locator("audio").wait_for(state="attached", timeout=5000)
    pop.locator("audio").evaluate("a => a.dispatchEvent(new Event('play'))")
    page.wait_for_timeout(100)
    bars_on = pop.locator(".u-eq").count() == 1
    pop.locator("audio").evaluate("a => a.dispatchEvent(new Event('pause'))")
    page.wait_for_timeout(100)
    bars_off = pop.locator(".u-eq").count() == 0
    page.context.close()
    got = dict(menu_ok=menu_ok, slid_fwd=slid_fwd, slid_back=slid_back, waving=waving, words=words >= 6,
               leaving=leaving, gone=gone, bars_on=bars_on, bars_off=bars_off)
    assert all(got.values()), got


def test_wide_screens_put_the_side_space_to_work(browser):
    """At 1920px the main area has room for rails: a sticky outline of the day
    (jumps to a card, marks the one being read) and the path ahead. At 1440 with
    the sidebar open there isn't, and the page stays one column."""
    page, _ = new_page(browser, "dark", "desktop")
    page.set_viewport_size({"width": 1920, "height": 1080})
    goto(page, "/feed")
    outline = page.get_by_role("navigation", name="Today's cards")
    got = {"outline": outline.is_visible(),
           "items": outline.get_by_role("button").count() == page.locator(".u-read-card").count()}
    target = outline.get_by_role("button").nth(2)
    target.click()
    page.wait_for_timeout(1200)
    got["jumps"] = target.get_attribute("aria-current") == "true"
    got["sticky"] = outline.bounding_box()["y"] < 200
    got["path_in_rail"] = page.get_by_role("complementary", name="Your path").count() == 1
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(400)
    got["narrow_hides"] = page.get_by_role("navigation", name="Today's cards").count() == 0
    page.context.close()
    assert all(got.values()), got


def test_your_path_numbers_match_the_day_menu(browser):
    """The path's first entry is the next lesson to generate (the server calls it
    "today"), and its later entries carry the server's internal lesson count —
    neither matched the Day labels the rest of the feed uses."""
    page, _ = new_page(browser, "dark", "desktop")
    goto(page, "/feed")
    path = page.get_by_text("Your path", exact=True).locator("xpath=..")
    path.wait_for(timeout=10000)
    text = path.inner_text()
    page.get_by_role("button", name=DAY_BUTTON).first.click()
    page.wait_for_timeout(400)
    row = page.locator(".u-menu").get_by_role("button", name=GENERATE_ROW).inner_text()
    next_label = _re.search(r"day \d+(\.\d+)?", row, _re.I).group(0)
    page.context.close()
    got = {"no_today": "TODAY" not in text.upper().split(),
           "up_next_matches_menu": f"up next · {next_label}".lower() in text.lower(),
           "no_internal_numbers": not _re.search(r"^day \d+$", text, _re.I | _re.M)}
    assert all(got.values()), (got, text, next_label)


GENERATE_ROW = _re.compile(r"^(generate|building) day", _re.I)


def _admin_row(i, trace, ok=True, starred=False):
    return {"id": i, "run_id": f"r{i}", "parent_run_id": None, "timestamp_start": "2026-10-01 10:00:00",
            "timestamp_end": "2026-10-01 10:00:01", "latency_ms": 120, "provider": "gemini",
            "model_requested": "gemini-2.5-flash", "model_used": "gemini-2.5-flash", "call_type": "explain",
            "user_id": "u1", "user_email": "a@example.com", "project_id": None, "day_ref": None,
            "input": "in", "output": "out", "input_tokens": 5, "output_tokens": 5, "total_tokens": 10,
            "success": ok, "error_type": None, "error_message": None, "retry_count": 0,
            "created_at": "2026-10-01 10:00:00", "starred": starred}
