"""Performance trace + bundle sizes, and the budget check between two runs.

    python -m scripts.ui_motion.perf baseline --frontend <pre-change checkout>/frontend
    python -m scripts.ui_motion.perf after
    python -m scripts.ui_motion.perf --compare baseline after

Measured on the production build, served by `vite preview`: that is what users
load, and a dev-server trace swings too much to compare (same code measured
0, 2 and 3 long tasks in three runs). Each trace is the median of three.
"""
import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from .session import API_URL, OUT, ROOT, new_page

FRONTEND = ROOT / "frontend"
PREVIEW_PORT = 5174        # in the backend's CORS allow-list (backend/config/app_config.py)
INITIAL_BUDGET = 25_600    # bytes gz — signed off by the user 2026-10-02 after measuring +24.7 KB (Motion core in Rollup ≈ 15.8 KB)
LAZY_BUDGET = 30_720


def build(frontend: Path) -> None:
    # resolved path, list args: no shell, and works where npm is npm.cmd (Windows)
    env = {**os.environ, "VITE_API_URL": API_URL}
    subprocess.run([shutil.which("npm"), "run", "build"], cwd=frontend, env=env, check=True, capture_output=True)


def bundle_sizes(frontend: Path) -> dict:
    dist = frontend / "dist"
    html = (dist / "index.html").read_text(encoding="utf-8")
    initial = set(re.findall(r'(?:src|href)="/(assets/[^"]+\.(?:js|css))"', html))
    sizes = {f.relative_to(dist).as_posix(): len(gzip.compress(f.read_bytes()))
             for f in (dist / "assets").iterdir() if f.suffix in (".js", ".css")}
    return {
        "initial_gz": sum(v for k, v in sizes.items() if k in initial),
        "lazy_motion_gz": sum(v for k, v in sizes.items() if "motionFeatures" in k),
        "files": sizes,
    }


def _trace_once(browser, base: str) -> dict:
    page, _ = new_page(browser, "light", "desktop")
    page.goto(base + "/feed")
    page.wait_for_selector("aside", state="attached", timeout=30000)
    page.wait_for_timeout(2500)
    # "toplevel" carries the per-task events; devtools.timeline alone has none.
    browser.start_tracing(page=page, categories=["toplevel", "devtools.timeline"])
    page.mouse.move(900, 500)
    for _ in range(12):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(120)
    for name in ("Dashboard", "Bookmarks", "Feed", "Chat", "Feed"):
        page.get_by_role("link", name=name, exact=True).first.click()
        page.wait_for_timeout(600)
    events = json.loads(browser.stop_tracing())["traceEvents"]
    page.context.close()
    # Long tasks are a main-thread measure: only the renderer's main thread counts.
    main = {(e["pid"], e["tid"]) for e in events
            if e.get("name") == "thread_name" and e.get("args", {}).get("name") == "CrRendererMain"}
    tasks = [e.get("dur", 0) / 1000 for e in events
             if e.get("name") in ("RunTask", "ThreadControllerImpl::RunTask")
             and (e.get("pid"), e.get("tid")) in main]
    return {"long_tasks": sum(t > 50 for t in tasks), "worst_ms": round(max(tasks, default=0), 1),
            "main_tasks": len(tasks)}


def trace(frontend: Path, runs: int = 3) -> dict:
    server = subprocess.Popen(
        [shutil.which("npx"), "vite", "preview", "--port", str(PREVIEW_PORT), "--strictPort"],
        cwd=frontend, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://localhost:{PREVIEW_PORT}"
    try:
        for _ in range(60):
            try:
                urlopen(base, timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            samples = [_trace_once(browser, base) for _ in range(runs)]
            browser.close()
    finally:
        if os.name == "nt":   # npx starts a child node process; take the whole tree down
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(server.pid)], capture_output=True)
        else:
            server.terminate()
    mid = sorted(samples, key=lambda s: s["long_tasks"])[len(samples) // 2]
    return {"long_tasks": mid["long_tasks"],
            "worst_ms": sorted(s["worst_ms"] for s in samples)[len(samples) // 2],
            "samples": samples}


def compare(before: str, after: str) -> None:
    b = json.loads((OUT / before / "perf.json").read_text())
    a = json.loads((OUT / after / "perf.json").read_text())
    growth = a["bundle"]["initial_gz"] - b["bundle"]["initial_gz"]
    lazy = a["bundle"]["lazy_motion_gz"]
    print(f"initial growth {growth} B (budget {INITIAL_BUDGET}); lazy motion {lazy} B (budget {LAZY_BUDGET}); "
          f"long tasks (median of 3) {b['trace']['long_tasks']} -> {a['trace']['long_tasks']}")
    assert growth <= INITIAL_BUDGET, "initial bundle over budget"
    assert lazy <= LAZY_BUDGET, "lazy motion chunk over budget"
    assert a["trace"]["long_tasks"] <= b["trace"]["long_tasks"] + 1, "more long tasks than baseline"
    print("budgets OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("after", nargs="?")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--frontend", type=Path, default=FRONTEND)
    args = ap.parse_args()
    # long form: Vite mis-computes asset paths when the root arrives as an 8.3 short name
    args.frontend = args.frontend.resolve()
    if args.compare:
        compare(args.label, args.after)
    else:
        out = OUT / args.label
        out.mkdir(parents=True, exist_ok=True)
        build(args.frontend)
        result = {"bundle": bundle_sizes(args.frontend), "trace": trace(args.frontend)}
        (out / "perf.json").write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result["bundle"].items() if k != "files"}
                         | {k: v for k, v in result["trace"].items() if k != "samples"}))
