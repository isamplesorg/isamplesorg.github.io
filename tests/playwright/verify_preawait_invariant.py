#!/usr/bin/env python3
"""
Prove the pre-await invalidation invariant (coherence audit F2).

Scenario: throttle the link, wait for a settled Explorer, then toggle a source
filter. The handler does a long awaited globe reload before recomputing counts.

BEFORE the fix: counts keep displaying the PREVIOUS filter's numbers, unmarked,
for the whole reload.
AFTER  the fix: counts are invalidated synchronously — dimmed at once and swapped
to "(Loading…)" once the wait exceeds the 400 ms grace period.

Usage: verify_invariant.py BASE_URL [--throttle KBPS]
"""
import sys, time, json
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8908"
KBPS = 400
if "--throttle" in sys.argv:
    KBPS = int(sys.argv[sys.argv.index("--throttle") + 1])

SNAP = """() => {
  const els = Array.from(document.querySelectorAll('.facet-count'));
  const txt = els.map(e => e.textContent.trim());
  return {
    n: els.length,
    recomputing: els.filter(e => e.classList.contains('recomputing')).length,
    unavailable: els.filter(e => e.classList.contains('count-unavailable')).length,
    loading_text: txt.filter(t => t.includes('Loading')).length,
    numeric_text: txt.filter(t => /\\(\\d/.test(t)).length,
    sample: txt.slice(0, 3),
  };
}"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")

    page.goto(f"{BASE}/explorer.html", wait_until="commit")
    print("waiting for a settled Explorer (unthrottled)...")
    for _ in range(180):
        if page.evaluate("() => document.querySelectorAll('.facet-treenode').length") > 0:
            break
        time.sleep(1)
    time.sleep(6)

    before = page.evaluate(SNAP)
    print(f"\nSETTLED: {before}")
    if before["numeric_text"] == 0:
        print("!! counts never became numeric; cannot run the experiment"); sys.exit(2)

    # Throttle hard so the awaited globe reload is unmistakably long.
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "downloadThroughput": KBPS * 1000 / 8,
        "uploadThroughput": KBPS * 1000 / 8,
        "latency": 500,
    })
    print(f"\nthrottled to {KBPS} kbps; toggling a source filter...")

    page.evaluate("""() => {
        const cb = document.querySelector('#sourceFilter input[type=checkbox]');
        if (cb) { cb.checked = !cb.checked;
                  cb.dispatchEvent(new Event('change', {bubbles: true})); }
    }""")

    # Sample densely across the awaited reload.
    obs = []
    t0 = time.time()
    for _ in range(50):
        time.sleep(0.4)
        try:
            s = page.evaluate(SNAP)
        except Exception:
            continue
        s["t"] = round(time.time() - t0, 1)
        obs.append(s)
        if s["t"] > 18:
            break

    print("\n  t     n  recomp  unavail  loadingTxt  numericTxt  sample")
    for s in obs[:24]:
        print(f"  {s['t']:>4}s {s['n']:>3} {s['recomputing']:>6} {s['unavailable']:>8} "
              f"{s['loading_text']:>11} {s['numeric_text']:>11}  {s['sample'][:2]}")

    # --- verdict --------------------------------------------------------------
    first = obs[0] if obs else None
    dimmed_fast = first and first["recomputing"] == first["n"] and first["n"] > 0
    ever_loading = any(o["loading_text"] > 0 for o in obs)
    stale_unmarked = [o for o in obs
                      if o["numeric_text"] > 0 and o["recomputing"] == 0
                      and o["unavailable"] == 0 and o["t"] < 12]

    print("\n=== VERDICT ===")
    print(f"  invalidated within ~0.4s of the toggle : {dimmed_fast}")
    print(f"  text swapped to (Loading…) during wait : {ever_loading}")
    print(f"  windows showing stale UNMARKED numbers : {len(stale_unmarked)}")
    ok = dimmed_fast and not stale_unmarked
    print(f"\n  INVARIANT HOLDS: {ok}")
    ctx.close(); b.close()
    sys.exit(0 if ok else 1)
