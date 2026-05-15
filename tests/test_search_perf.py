"""
Search perf-smoke baseline (#167, Track 1a of #165).

Drives the canonical query set against the deployed Explorer and records
per-search timings + bytes-transferred for each query, both cold (fresh
page context) and warm (immediate repeat on the same page).

Cold here means file-cold: a fresh browser context, no DuckDB-WASM cache,
no HTTP cache. Warm means a second invocation of the same query on the
same page after the cold run completes.

Usage:

    # Against the deployed site (default):
    pytest tests/test_search_perf.py -s

    # Against a local Quarto preview:
    ISAMPLES_BASE_URL=http://localhost:5860 pytest tests/test_search_perf.py -s

    # Against a deployed PR preview:
    ISAMPLES_BASE_URL=https://<preview-host> pytest tests/test_search_perf.py -s

The benchmark JSON is written to:

    tests/search_baseline_<UTC_DATE>.json

This is slow (~8-15 minutes total) because each query opens a fresh context
to capture true file-cold timings. Run as a release-time benchmark, not on
every CI invocation.

Open design questions tracked on issue #167.
"""
import datetime as dt
import json
import os
import pathlib
import pytest
from conftest import SITE_URL


EXPLORER_URL = f"{SITE_URL}/explorer.html?perf=1"

# Canonical query set (locked in #167). Each entry drives one cold + one
# warm measurement. Filter-composition cases set source/facet selections
# before searching.
CANONICAL_QUERIES = [
    {"label": "single-common",   "term": "pottery",        "filters": {}},
    {"label": "single-rare",     "term": "basalt",         "filters": {}},
    {"label": "multi-term",      "term": "pottery Cyprus", "filters": {}},
    {"label": "no-hit",          "term": "xyzzyqqqplugh",  "filters": {}},
    {"label": "wildcard-pct",    "term": "100%",           "filters": {}},
    {"label": "wildcard-under",  "term": "_test",          "filters": {}},
    {"label": "diacritic",       "term": "Çatalhöyük",     "filters": {}},
    {
        "label": "composed-source",
        "term": "pottery",
        "filters": {"source_only": ["OPENCONTEXT"]},
    },
    {
        # Pairs source restriction with a material-facet selection so the
        # benchmark exercises the facetFilterSQL() pid-IN-subquery path,
        # not just sourceFilterSQL(). The first material checkbox is used
        # to keep the test stable across data refreshes (don't hard-code a
        # URI that may disappear between snapshots).
        "label": "composed-source-material",
        "term": "pottery",
        "filters": {
            "source_only": ["OPENCONTEXT"],
            "material_first_n": 1,
        },
    },
    {
        # Viewport-scoped search per #178 Light path. Camera position is
        # set via the URL hash (Mediterranean / Cyprus area) so the
        # area-scope predicate has a meaningful rect. Area scope is routed
        # via ?search_scope=area in the URL (see _measure_one_query).
        "label": "area-scope",
        "term": "pottery",
        "filters": {"scope": "area"},
        "url_hash": "v=1&lat=35&lng=33&alt=2000000",
    },
]


def _wait_for_explorer_ready(page, timeout_ms: int = 90_000) -> None:
    """Wait until DuckDB-WASM has loaded facets — proxy for "ready to search"."""
    page.wait_for_function(
        """() => {
            const el = document.querySelector(
                ".facet-count[data-facet='source'][data-value='SESAR']"
            );
            return el && /\\(\\d/.test(el.textContent || '');
        }""",
        timeout=timeout_ms,
    )


def _wait_for_facet_settle(page, timeout_ms: int = 30_000) -> None:
    """Block until all change-triggered async work has fully settled.

    Two-phase wait, matching the app's two-stage settle (#173 review):

      1. body.classList.contains('explorer-busy') is set by the source /
         material / context / object_type change handlers around their
         async work. We wait for it to clear — guarantees that loadRes,
         loadViewportSamples, and the 250 ms refreshFacetCounts debounce
         have all fired.
      2. .facet-count.recomputing is set during the actual cross-filter
         query and cleared as each dimension's results arrive. We wait
         for it to clear — guarantees the in-flight count queries are
         done.

    Polling either signal alone races: just-recomputing because the
    debounce hasn't fired yet, just-busy because the change handler
    chose a different work path.
    """
    page.wait_for_function(
        """() => !document.body.classList.contains('explorer-busy')""",
        timeout=timeout_ms,
    )
    page.wait_for_function(
        """() => {
            const recomputing = document.querySelectorAll('.facet-count.recomputing');
            return recomputing.length === 0;
        }""",
        timeout=timeout_ms,
    )


def _apply_source_filter(page, sources_to_keep_checked: list[str]) -> None:
    """Uncheck source checkboxes that aren't in the keep list."""
    all_sources = ["SESAR", "OPENCONTEXT", "GEOME", "SMITHSONIAN"]
    changed = False
    for src in all_sources:
        cb = page.locator(f"#sourceFilter input[type='checkbox'][value='{src}']")
        is_checked = cb.is_checked()
        should_be_checked = src in sources_to_keep_checked
        if is_checked != should_be_checked:
            cb.click()
            changed = True
    if changed:
        _wait_for_facet_settle(page)


def _apply_material_first_n(page, n: int) -> None:
    """Check the first n material-facet checkboxes (avoids hard-coding URIs).

    The material filter section ships with `display: none` on the body
    (explorer.qmd:280); the header click handler toggles it. Expand the
    section before attempting to click any checkbox inside it.
    """
    if n <= 0:
        return
    boxes = page.locator("#materialFilterBody input[type='checkbox']")
    boxes.first.wait_for(state="attached", timeout=15_000)
    body_hidden = page.evaluate(
        "() => document.getElementById('materialFilterBody').style.display === 'none'"
    )
    if body_hidden:
        page.locator("#materialFilter .filter-header").click()
    total = boxes.count()
    for i in range(min(n, total)):
        cb = boxes.nth(i)
        if not cb.is_checked():
            cb.click()
    _wait_for_facet_settle(page)


def _run_search(
    page,
    term: str,
    *,
    captured: list,
    expected_id_after: int,
) -> dict:
    """Type term, click the visible submit button, wait for the console event.

    The slim overlay (PR #224) hides the per-scope buttons (`display: none`),
    so Playwright can no longer click them. Scope is instead routed through
    `_searchScope`, which the page hydrates from `?search_scope=area` in the
    URL — `_measure_one_query` sets that param up front. `#searchSubmitBtn`
    is the same public path a keyboard/mouse user now exercises.
    """
    search_input = page.locator("#sampleSearch")
    search_input.click()
    # Clear via select-all + delete (faster + works around platform shortcuts).
    search_input.press("ControlOrMeta+a")
    search_input.press("Delete")
    search_input.fill(term)
    page.locator("#searchSubmitBtn").click()

    # Wait for an isamples.search log whose id is strictly greater than the
    # last one we observed. Polling is simpler than promise-based waits here.
    deadline = page.evaluate("() => Date.now()") + 90_000
    while True:
        for entry in captured:
            if entry.get("id", -1) > expected_id_after and entry.get("term") == term:
                return entry
        if page.evaluate("() => Date.now()") > deadline:
            raise TimeoutError(f"No isamples.search log captured for term={term!r}")
        page.wait_for_timeout(250)


def _collect_search_logs(page, captured: list) -> None:
    """Attach a console listener that parses isamples.search JSON events."""
    def _on_console(msg):
        if msg.type != "log":
            return
        text = msg.text
        if "isamples.search" not in text:
            return
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return
        if isinstance(payload, dict) and payload.get("event") == "isamples.search":
            captured.append(payload)
    page.on("console", _on_console)


def _measure_one_query(browser, query: dict) -> dict:
    """Open fresh context, run cold + warm, return aggregated record.

    try/finally on context.close() so a timeout in _run_search (or any
    intermediate step) does not leak the browser context, which would
    skew later measurements (#173 review).
    """
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        captured: list = []
        _collect_search_logs(page, captured)

        filters = query["filters"]
        scope = filters.get("scope", "world")

        # Area scope is hydrated from `?search_scope=area` (EXPLORER_URL
        # already carries `?perf=1`, so append with `&`). The slim overlay
        # hides the scope buttons, so the URL param is the public path the
        # UI now uses to route to the area-scoped query.
        scope_param = "&search_scope=area" if scope == "area" else ""
        # Optional URL hash for area-scope cases (#178) — sets the camera
        # before the search runs so the area predicate has a meaningful rect.
        url_hash = query.get("url_hash")
        target_url = (
            EXPLORER_URL + scope_param + (f"#{url_hash}" if url_hash else "")
        )
        page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        _wait_for_explorer_ready(page)

        if "source_only" in filters:
            _apply_source_filter(page, filters["source_only"])
        if "material_first_n" in filters:
            _apply_material_first_n(page, filters["material_first_n"])

        cold = _run_search(
            page, query["term"], captured=captured, expected_id_after=0,
        )
        warm = _run_search(
            page, query["term"], captured=captured, expected_id_after=cold["id"],
        )
    finally:
        context.close()
    return {
        "label": query["label"],
        "term": query["term"],
        "filters": query["filters"],
        "cold": cold,
        "warm": warm,
    }


def _utc_now() -> dt.datetime:
    """Aware UTC datetime; replaces the deprecated dt.datetime.utcnow()."""
    return dt.datetime.now(dt.timezone.utc)


@pytest.fixture(scope="session")
def benchmark_run_started_at() -> dt.datetime:
    return _utc_now()


@pytest.fixture(scope="session")
def baseline_output_path(benchmark_run_started_at) -> pathlib.Path:
    stamp = benchmark_run_started_at.strftime("%Y-%m-%d")
    path = pathlib.Path(__file__).parent / f"search_baseline_{stamp}.json"
    return path


def test_record_search_baseline(browser, benchmark_run_started_at, baseline_output_path):
    """Run the canonical query set, dump JSON. Single test = one benchmark run."""
    results = []
    failures = []
    for query in CANONICAL_QUERIES:
        try:
            record = _measure_one_query(browser, query)
        except Exception as exc:
            record = {
                "label": query["label"],
                "term": query["term"],
                "filters": query["filters"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            failures.append(record)
        results.append(record)
        # Stream to stdout so partial runs are still useful.
        print(json.dumps(record, indent=2))

    payload = {
        "site_url": SITE_URL,
        "captured_at_utc": benchmark_run_started_at.isoformat(),
        "schema_version": 1,
        "field_subset": "label+description+place_name (sample_facets_v2 + lite for coords; world via LEFT JOIN, area via INNER JOIN with viewport predicate inside CTE)",
        "queries": results,
    }
    baseline_output_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWrote baseline to {baseline_output_path}")

    # A benchmark with silent failures is a poisoned baseline — refuse to
    # treat it as valid. Partial data is still on disk for diagnosis.
    incomplete = [
        r for r in results
        if "error" in r
        or "cold" not in r
        or r.get("cold", {}).get("elapsed_ms") is None
        or "warm" not in r
        or r.get("warm", {}).get("elapsed_ms") is None
    ]
    assert not incomplete, (
        f"{len(incomplete)}/{len(CANONICAL_QUERIES)} queries did not complete cleanly. "
        f"Failed labels: {[r['label'] for r in incomplete]}. "
        f"Partial data at {baseline_output_path}."
    )
