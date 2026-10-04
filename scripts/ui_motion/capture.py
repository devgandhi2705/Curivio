"""Screenshot every screen in every theme at phone and desktop width, run the
flows once per combination, and save the console errors seen along the way.

    python -m scripts.ui_motion.capture baseline
"""
import json
import sys

from playwright.sync_api import sync_playwright

from .session import OUT, SCREENS, THEMES, WIDTHS, goto, new_page, normalize, run_flows


def main(label: str) -> None:
    out = OUT / label
    out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in THEMES:
            for width in WIDTHS:
                page, errors = new_page(browser, theme, width)
                for name, path in SCREENS.items():
                    goto(page, path)
                    page.screenshot(path=str(out / f"{width}-{theme}-{name}.png"))
                run_flows(page, width)
                page.screenshot(path=str(out / f"{width}-{theme}-chat-answered.png"))
                seen |= normalize(errors)
                page.context.close()
        browser.close()
    (out / "console.json").write_text(json.dumps(sorted(seen), indent=2))
    print(f"{label}: {len(list(out.glob('*.png')))} screenshots, {len(seen)} distinct console errors")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "baseline")
