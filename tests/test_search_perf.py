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


def _apply_source_filter(page, sources_to_keep_checked: list[str]) -> None:
    """Uncheck source checkboxes that aren't in the keep list."""
    all_sources = ["SESAR", "OPENCONTEXT", "GEOME", "SMITHSONIAN"]
    for src in all_sources:
        cb = page.locator(f"#sourceFilter input[type='checkbox'][value='{src}']")
        is_checked = cb.is_checked()
        should_be_checked = src in sources_to_keep_checked
        if is_checked != should_be_checked:
            cb.click()
    # Let the change handler debounce settle.
    page.wait_for_timeout(800)


def _run_search(page, term: str, *, captured: list, expected_id_after: int) -> dict:
    """Type term, click search, wait for the corresponding console event."""
    search_input = page.locator("#sampleSearch")
    search_input.click()
    # Clear via select-all + delete (faster + works around platform shortcuts).
    search_input.press("ControlOrMeta+a")
    search_input.press("Delete")
    search_input.fill(term)
    page.locator("#searchBtn").click()

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
    """Open fresh context, run cold + warm, return aggregated record."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    captured: list = []
    _collect_search_logs(page, captured)
    page.goto(EXPLORER_URL, wait_until="domcontentloaded", timeout=60_000)
    _wait_for_explorer_ready(page)

    if "source_only" in query["filters"]:
        _apply_source_filter(page, query["filters"]["source_only"])

    cold = _run_search(page, query["term"], captured=captured, expected_id_after=0)
    warm = _run_search(
        page, query["term"], captured=captured, expected_id_after=cold["id"]
    )

    context.close()
    return {
        "label": query["label"],
        "term": query["term"],
        "filters": query["filters"],
        "cold": cold,
        "warm": warm,
    }


@pytest.fixture(scope="session")
def baseline_output_path() -> pathlib.Path:
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    path = pathlib.Path(__file__).parent / f"search_baseline_{today}.json"
    return path


def test_record_search_baseline(browser, baseline_output_path):
    """Run the canonical query set, dump JSON. Single test = one benchmark run."""
    results = []
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
        results.append(record)
        # Stream to stdout so partial runs are still useful.
        print(json.dumps(record, indent=2))

    payload = {
        "site_url": SITE_URL,
        "captured_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "schema_version": 1,
        "field_subset": "label+place_name (samples_map_lite.parquet)",
        "queries": results,
    }
    baseline_output_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWrote baseline to {baseline_output_path}")

    # Light sanity check: at least half the queries produced a usable cold record.
    completed = sum(
        1 for r in results
        if "cold" in r and r["cold"].get("elapsed_ms") is not None
    )
    assert completed >= len(CANONICAL_QUERIES) // 2, (
        f"Only {completed}/{len(CANONICAL_QUERIES)} queries completed cleanly; "
        f"see {baseline_output_path} for partial data"
    )
