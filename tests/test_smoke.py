"""
Pre-deploy smoke test (Option C) — the gate that catches a JS-dead render.

WHY THIS EXISTS
---------------
The deploy workflow runs `quarto render` and ships whatever `docs/` it
produces. Neither Codex review nor `pytest --collect-only` ever *loads*
the rendered page in a browser, so a render that "succeeds" but yields a
page where DuckDB-WASM never inits, Cesium never draws, or search returns
nothing has historically deployed to isamples.org anyway. This test closes
exactly that gap: it is run in CI against the freshly-rendered `docs/`
(served locally) *before* the Deploy step. If it fails, the job fails and
the deploy never happens (fail-closed).

DESIGN CONSTRAINTS (learned the hard way)
-----------------------------------------
- ONE fresh context, ONE navigation, poll-for-readiness. Hammering the
  page with rapid reloads exhausts the DuckDB-WASM worker and produces
  *false* failures — a test-harness artifact, not a real break. Never
  add a reload loop here.
- Assert only on unambiguous "fundamentally alive" signals so a benign
  console warning can't block a deploy: DuckDB-WASM inits, Cesium draws,
  a search returns results, and no *uncaught* JS exception fired.
- Self-contained: does NOT import the slow CANONICAL_QUERIES benchmark
  from test_search_perf.py. This must stay fast (well under a minute).

Run locally against the rendered output:

    cd docs && python -m http.server 8080 &
    ISAMPLES_BASE_URL=http://localhost:8080 pytest tests/test_smoke.py -s
"""
import re

import pytest
from conftest import SITE_URL

EXPLORER_URL = f"{SITE_URL}/explorer.html?perf=1"

# DuckDB-WASM is "alive" once it has run the facet query and written a
# numeric count into the SESAR source facet. Same proxy the perf test
# uses for "ready to search".
_READY_JS = """() => {
    const el = document.querySelector(
        ".facet-count[data-facet='source'][data-value='SESAR']"
    );
    return el && /\\(\\d/.test(el.textContent || '');
}"""

# High-signal regression fingerprints. We do NOT fail on every console
# error (benign third-party noise would block deploys); we DO fail on
# uncaught exceptions (pageerror) and on these specific "the JS broke"
# strings, which are what an OJS/scope/undefined-symbol regression emits.
_FATAL_CONSOLE = re.compile(
    r"is not defined|is not a function|Cannot read propert|"
    r"Uncaught|SyntaxError|ReferenceError",
    re.IGNORECASE,
)


def test_explorer_smoke(browser):
    """Fundamental-liveness gate for explorer.html. Fail-closed in CI."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()

    page_errors: list[str] = []
    fatal_console: list[str] = []
    page.on("pageerror", lambda e: page_errors.append(str(e)))

    def _on_console(msg):
        if msg.type == "error" and _FATAL_CONSOLE.search(msg.text or ""):
            fatal_console.append(msg.text)

    page.on("console", _on_console)

    try:
        # Single navigation. ?perf=1 matches what the perf test / users hit.
        page.goto(EXPLORER_URL, wait_until="domcontentloaded", timeout=60_000)

        # 1. DuckDB-WASM initialized (facet query ran). Poll, do not reload.
        page.wait_for_function(_READY_JS, timeout=90_000)

        # 2. Cesium actually drew a globe (canvas attached), not just a
        #    container div.
        page.wait_for_selector(
            ".cesium-viewer .cesium-widget canvas",
            state="attached",
            timeout=30_000,
        )

        # 3. A world search via the *visible* slim-overlay submit button
        #    returns results. "pottery" is a high-frequency term, so a
        #    healthy build always returns >=1; zero/blank means broken
        #    search wiring or a dead query path.
        search = page.locator("#sampleSearch")
        search.click()
        search.fill("pottery")
        page.locator("#searchSubmitBtn").click()
        page.wait_for_function(
            """() => {
                const el = document.getElementById('searchResults');
                const t = (el && el.textContent || '').trim();
                return t && !/Searching/i.test(t) && /result/i.test(t);
            }""",
            timeout=60_000,
        )
        results_text = page.locator("#searchResults").inner_text().strip()

        # 4. No uncaught JS exception and no regression-fingerprint
        #    console error fired during the whole flow.
        assert not page_errors, f"Uncaught JS exception(s): {page_errors}"
        assert not fatal_console, f"Fatal console error(s): {fatal_console}"

        # Sanity: the result line must actually carry a count.
        assert re.search(r"\d", results_text), (
            f"Search returned no countable results: {results_text!r}"
        )
        print(f"SMOKE OK — search result: {results_text!r}")
    finally:
        context.close()
